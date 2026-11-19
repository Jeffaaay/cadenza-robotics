"""Replay recorded OpenArm observations through policies; never connect to a robot."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time
import traceback
from datetime import datetime, timezone


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def frame_at(path, target, fps):
    import av
    import numpy as np

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        container.seek(int(target / float(stream.time_base)), stream=stream, backward=True)
        candidates = []
        for frame in container.decode(stream):
            if frame.time is None:
                continue
            candidates.append(frame)
            candidates = candidates[-2:]
            if frame.time >= target - 1e-7:
                break
        if not candidates:
            raise ValueError(f"No video frame at {target}")
        frame = min(candidates, key=lambda item: abs(item.time - target))
        error = float(frame.time - target)
        if abs(error) > 0.51 / fps + 1e-4:
            raise ValueError(f"Video alignment error {error} seconds")
        rgb = np.ascontiguousarray(frame.to_ndarray(format="rgb24"))
        return rgb, {"requested_seconds": target, "decoded_seconds": frame.time,
                     "error_seconds": error, "rgb_sha256": hashlib.sha256(rgb.tobytes()).hexdigest()}


def load_observations(assets, model, episode):
    import numpy as np
    import pandas as pd
    import torch

    root = assets / f"{model}-data"
    info = read_json(root / "meta/info.json")
    episodes = pd.read_parquet(root / "meta/episodes/chunk-000/file-000.parquet")
    metadata = episodes.loc[episodes.episode_index == episode].iloc[0]
    path = info["data_path"].format(chunk_index=int(metadata["data/chunk_index"]),
                                    file_index=int(metadata["data/file_index"]))
    data = pd.read_parquet(root / path)
    data = data.loc[data.episode_index == episode].sort_values("frame_index")
    tasks = pd.read_parquet(root / "meta/tasks.parquet")
    observations, provenance = [], []
    for index in (0, 10, 20, 30, 40):
        row = data.loc[data.frame_index == index].iloc[0]
        task_index = int(row.task_index)
        task = str(tasks.loc[tasks.task_index == task_index].index[0])
        state = np.asarray(row["observation.state"], dtype=np.float32)
        expected = 8 if model == "smolvla" else 16
        if state.shape != (expected,) or not np.isfinite(state).all():
            raise ValueError(f"Invalid state shape/values: {state.shape}")
        obs = {"observation.state": torch.from_numpy(state.copy()), "task": task}
        record = {"episode": episode, "frame": index, "dataset_index": int(row["index"]),
                  "task": task, "state": state.tolist(), "images": {}}
        for key, feature in info["features"].items():
            if feature["dtype"] != "video":
                continue
            video = info["video_path"].format(video_key=key,
                chunk_index=int(metadata[f"videos/{key}/chunk_index"]),
                file_index=int(metadata[f"videos/{key}/file_index"]))
            target = float(metadata[f"videos/{key}/from_timestamp"]) + float(row.timestamp)
            rgb, alignment = frame_at(root / video, target, info["fps"])
            if list(rgb.shape) != feature["shape"]:
                raise ValueError(f"Unexpected camera resolution {key}: {rgb.shape}")
            obs[key] = torch.from_numpy(rgb).permute(2, 0, 1).float().div(255)
            record["images"][key] = {"shape_hwc": list(rgb.shape), **alignment}
        observations.append(obs)
        provenance.append(record)
    return observations, provenance, info


def run(args, result):
    print("Loading runtime and verifying recorded assets...", flush=True)
    import torch
    from safetensors.torch import load_file
    from lerobot.configs import PreTrainedConfig
    from lerobot.policies.factory import get_policy_class, make_pre_post_processors

    if not torch.cuda.is_available():
        raise RuntimeError("This benchmark requires CUDA; no silent CPU fallback")
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.set_num_threads(8)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    assets = args.assets.resolve()
    manifest = read_json(assets / "manifest.json")
    aliases = {args.model, args.model + "-data"} | ({"vlm"} if args.model == "smolvla" else set())
    result["sources"] = {key: value for key, value in manifest["sources"].items() if key in aliases}
    for item in manifest["files"]:
        if item["alias"] in aliases:
            with (assets / item["alias"] / item["path"]).open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                    raise ValueError(f"Source checksum mismatch: {item['path']}")
    result["environment"] = {
        "os": platform.system() + " " + platform.release(), "python": platform.python_version(),
        "gpu": torch.cuda.get_device_name(), "cuda_runtime": torch.version.cuda,
        "compute_capability": list(torch.cuda.get_device_capability()),
        "gpu_total_mib": torch.cuda.get_device_properties(0).total_memory / 2**20,
        "gpu_free_mib_before_load": torch.cuda.mem_get_info()[0] / 2**20,
        "cpu_threads": torch.get_num_threads(),
        "packages": {name: importlib.metadata.version(name) for name in
            ["lerobot", "torch", "torchvision", "transformers", "huggingface-hub", "safetensors", "numpy", "av", "pandas", "pyarrow"]},
        "nvidia_smi": subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,power.limit", "--format=csv,noheader"], text=True).strip(),
    }
    observations, provenance, info = load_observations(assets, args.model, args.episode)
    print(f"Decoded {len(observations)} timestamp-aligned observations", flush=True)
    result["observations"] = provenance
    result["action_names"] = info["features"]["action"]["names"]
    root = assets / args.model
    cfg = PreTrainedConfig.from_pretrained(str(root))
    cfg.device = "cuda"
    overrides = {"device_processor": {"device": "cuda"}}
    result["overrides"] = {"device": "cuda"}
    if args.model == "smolvla":
        cfg.load_vlm_weights = False
        cfg.vlm_model_name = str(assets / "vlm")
        overrides["tokenizer_processor"] = {"tokenizer_name": str(assets / "vlm")}
        result["overrides"].update(load_vlm_weights=False, vlm_model_name="pinned local vlm assets",
            explanation="Initialize architecture locally; strict checkpoint load supplies ALL policy weights.")
        stats = load_file(str(root / "policy_preprocessor_step_5_normalizer_processor.safetensors"))
        result["normalizer_shapes"] = {key: list(value.shape) for key, value in stats.items() if key.startswith("observation.state")}
        result["declared_state_shape"] = list(cfg.input_features["observation.state"].shape)
        state_stats = [value for key, value in stats.items() if key.startswith("observation.state") and key.endswith(("mean", "std"))]
        if len(state_stats) != 2 or any(value.shape != (8,) for value in state_stats):
            raise ValueError("Checkpoint does not have eight-channel state mean/std")
    else:
        cfg.pretrained_backbone_weights = None
        result["overrides"]["pretrained_backbone_weights"] = None
    started = time.perf_counter()
    policy = get_policy_class(args.model).from_pretrained(str(root), config=cfg, strict=True).eval()
    pre, post = make_pre_post_processors(cfg, pretrained_path=str(root), preprocessor_overrides=overrides)
    torch.cuda.synchronize()
    result["load_seconds"] = time.perf_counter() - started
    result["parameter_count"] = sum(p.numel() for p in policy.parameters())
    result["parameter_dtypes"] = sorted({str(p.dtype) for p in policy.parameters()})
    result["parameter_count_by_dtype"] = {dtype: sum(p.numel() for p in policy.parameters() if str(p.dtype) == dtype)
                                           for dtype in result["parameter_dtypes"]}
    result["precision"] = {"parameter_dtypes": result["parameter_dtypes"], "autocast": False,
        "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_tf32": torch.backends.cudnn.allow_tf32}
    check = pre(observations[0])
    expected = 8 if args.model == "smolvla" else 16
    if check["observation.state"].shape != (1, expected):
        raise ValueError("Processor changed state channel count")
    result["processed_state_shape"] = list(check["observation.state"].shape)
    result["processed_image_keys"] = [key for key in check if key.startswith("observation.images.")]
    if args.model == "smolvla":
        padded = policy.prepare_state(check)
        assert torch.equal(padded[:, :8], check["observation.state"])
        assert torch.count_nonzero(padded[:, 8:]).item() == 0
        images, _ = policy.prepare_images(check)
        assert len(images) == 2
        result["smolvla_contract"] = {"retained_state_channels": 8, "padded_state_shape": list(padded.shape),
            "actual_cameras": 2, "unused_config_camera3": True, "num_steps": cfg.num_steps}
    del check

    def predict(obs):
        policy.reset()
        batch = pre(obs)
        action = policy.predict_action_chunk(batch)
        action = post(action).detach().float().cpu()
        return action

    with torch.inference_mode():
        print("Warming up twice, then timing five fresh chunks...", flush=True)
        for _ in range(2):
            predict(observations[0])
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats()
        runs = []
        for index, obs in enumerate(observations):
            torch.manual_seed(args.seed + index)
            torch.cuda.manual_seed_all(args.seed + index)
            torch.cuda.synchronize()
            start = time.perf_counter()
            action = predict(obs)
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            shape = [1, cfg.chunk_size, expected]
            if list(action.shape) != shape or not torch.isfinite(action).all():
                raise ValueError(f"Invalid action output: {list(action.shape)}")
            runs.append({"frame": provenance[index]["frame"], "seconds": elapsed,
                         "shape": shape, "all_finite": True, "actions": action[0].tolist()})
            print(f"{args.model}: frame {provenance[index]['frame']} {elapsed:.4f}s {shape}", flush=True)
    result["runs"] = runs
    latencies = [item["seconds"] for item in runs]
    result["timing"] = {"warmups": 2, "measured_runs": len(runs), "median_seconds": statistics.median(latencies),
        "min_seconds": min(latencies), "max_seconds": max(latencies),
        "boundary": "CPU decoded RGB/state -> preprocess -> fresh full chunk inference -> unnormalize -> CPU action; CUDA synchronized. Excludes video decode, loading and network."}
    result["peak_allocated_mib"] = torch.cuda.max_memory_allocated() / 2**20
    result["peak_reserved_mib"] = torch.cuda.max_memory_reserved() / 2**20
    result["status"] = "passed_offline_inference"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=("smolvla", "act"), required=True)
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20261119)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(args.assets.resolve() / "cache")
    os.environ["TORCH_HOME"] = str(args.assets.resolve() / "torch-cache")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    result = {"started_utc": stamp, "model": args.model, "episode": args.episode, "seed": args.seed,
        "status": "started", "scope": "Recorded-observation software inference only; no robot connection, no closed-loop evaluation, no PLA validation."}
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target = args.output / f"{args.model}-{stamp}.json"
    try:
        run(args, result)
    except Exception as error:
        result.update(status="failed", error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Result: {target}", flush=True)


if __name__ == "__main__":
    main()
