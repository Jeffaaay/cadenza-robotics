# OpenArm 离线模型实验

本实验在电脑上回放公开记录的图像与状态，检查完整动作预测、显存和延迟。没有连接机器人、采集本机示范、训练模型、运行闭环仿真或验证 PLA 承载能力。ACT 是这里额外选择的模仿学习基线，不是对用户所称“NCT”的改名。

## 2026-11-19 实测结果

运行主机：Windows、RTX 5060 Laptop（8151 MiB 显存）、约 32 GB RAM，NVIDIA 驱动 610.91；Python 3.12.10、PyTorch 2.7.1+cu128、LeRobot 0.6.1。CUDA 实际矩阵运算通过，依赖检查通过。它不是项目另一台历史订单所列的 4060 Ti 16 GB 台式机。

| 模型 / 阶段 | 输入与完整输出 | 5 次中位数 | 最小–最大 | PyTorch 分配 / 保留峰值 |
|---|---|---:|---:|---:|
| [SmolVLA / 首轮](results/smolvla-initial.json) | 2 路 RGB＋8 维状态 → 50×8 | 0.338 s | 0.332–0.353 s | 1218.9 / 1274.0 MiB |
| [SmolVLA / 复核](results/smolvla-verified.json) | 2 路 RGB＋8 维状态 → 50×8 | 0.338 s | 0.338–0.340 s | 1218.9 / 1274.0 MiB |
| [ACT / 首轮](results/act-initial.json) | 5 路 RGB＋16 维状态 → 100×16 | 0.207 s | 0.194–0.298 s | 1076.5 / 1384.0 MiB |
| [ACT / 复核](results/act-verified.json) | 5 路 RGB＋16 维状态 → 100×16 | 0.220 s | 0.195–0.302 s | 1076.5 / 1384.0 MiB |

四次运行均完成，每次五个完整动作块全部为有限数，模型权重严格加载通过。显存数据是预热后测量阶段的 PyTorch 峰值，不包含其他应用、驱动和加载时瞬时开销；该卡同时承担桌面显示。SmolVLA 复核保留 301,234,320 个 bfloat16 参数及 148,811,856 个 float32 参数；ACT 为 float32。

首轮 JSON 的 `precision` 描述字符串误写为全部 float32；同份记录的 `parameter_dtypes` 正确保留了 SmolVLA 的混合精度。已修正记录代码，重新完整运行两模型；首轮文件保留原样供审计。首轮脚本 SHA 与复核不同，变化限于进度输出与精度记录。没有失败或中止的模型推理尝试；环境安装与输入元信息检查不计作模型运行。

**结论：现有电脑可以开始这两种模型的离线实验。** 0.34 秒生成 50 步、0.22 秒生成 100 步，均指一次新动作块预测；不能把动作块长度除以耗时当成闭环反馈频率，也没有实际执行这段轨迹。

下一步沿固定上半身路线推进：先验证 PLA 接口/闭合梁、逐侧遥操作与停止行为，再录本机示范、校验动作单位/符号/零位与相机时间线。SmolVLA 的两视图单臂路线可作为首个软件候选；本检查点不能直接扩成 16 维双臂。ACT 五视图是这份仿真检查点的契约，不是要求立即购买五台相机。完成本机数据适配和受控闭环试验后，才能回答抓取、分类、布角移动的实际成功率；折叠和下半身继续后置。

## 复现

使用 Python 3.12、NVIDIA CUDA GPU。首次安装和下载需要网络及约十余 GB 的环境/缓存空间；数据和权重不进入 Git。以下 PowerShell 命令在仓库根目录运行：

```powershell
python -m venv work/model-venv
& work/model-venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
& work/model-venv/Scripts/python.exe -m pip install --cache-dir work/pip-cache -r experiments/offline-inference/requirements-lock.txt
& work/model-venv/Scripts/python.exe experiments/offline-inference/fetch_assets.py --assets work/model-assets
& work/model-venv/Scripts/python.exe experiments/offline-inference/benchmark.py --assets work/model-assets --output work/model-runs --model smolvla --episode 0
& work/model-venv/Scripts/python.exe experiments/offline-inference/benchmark.py --assets work/model-assets --output work/model-runs --model act --episode 24
```

两个推理命令按顺序执行，避免同时争抢 GPU。[sources.lock.json](sources.lock.json)固定模型、处理器、分词器、数据修订及每个文件的 SHA-256。下载程序校验大小与哈希；推理前再次校验。推理禁用 Hugging Face 网络访问。新增依赖仅装在独立环境中。

## 方法与边界

- 每个模型读取一个 episode 的第 0、10、20、30、40 帧，共五组不同输入。按 episode 视频起始时间加记录时间戳寻找最近帧；误差超过半帧便停止，记录解码时间、RGB 哈希与状态。
- 使用官方 LeRobot 0.6.1 的策略及预处理/后处理。模型严格加载完整检查点，任何缺失或多余权重都会失败。保留数据通道顺序、原始视图和分辨率，不为省显存删去双臂或相机。
- SmolVLA 只从已固定的 VLM 配置创建架构，再由完整策略检查点恢复权重；ACT 不另下载 ImageNet 初始化。两者没有随机权重残留。相应覆盖项保存在每次结果中。
- 保留模型实际参数精度：SmolVLA 为 bfloat16/float32 混合，ACT 为 float32；batch=1、autocast/TF32 关闭，CPU 线程数 8。两次预热后五次测量。每次调用 `predict_action_chunk` 生成新动作块，并在计时前后同步 CUDA。记录中位数、范围及 PyTorch 显存峰值。
- 计时包含 CPU 图像/状态输入、预处理、模型预测、反归一化与动作返回 CPU；不含视频解码、下载、模型加载、相机采集、通信和执行器。因此不是机器人端到端延迟。PyTorch 分配峰值也不是整台 GPU 的总占用。
- 检查全部输出有限且维度正确；没有用“非 NaN”代替动作正确性。保存原始动作块，不做实机限幅或下发。五个相邻观察不构成任务成功率或泛化评估。
- 每次尝试写独立 JSON，异常也保留。原始数值报告见本目录结果文件；复现运行写入用户选择的目录。

## 输入契约

SmolVLA 使用右臂七关节及夹爪共 8 维，胸部和右腕两路 RGB，指令来自记录。检查点配置遗留 `state=[6]` 和第三路相机；实际 mean/std 均为 8 维。代码检查预处理后为 `[1,8]`，补到 32 维时前八维不变、后面全零，实际使用两路图像。第三路在 `empty_cameras=0` 下不加入；没有截断状态或捏造第三幅图像。输出为 50×8。

ACT 使用双臂 16 维和 ceiling、head_left、head_right、wrist_left、wrist_right 五路图像，输出为 100×16。状态/动作顺序是右侧 8 维后接左侧 8 维；保留完整通道名称供后续接口核对。ACT 不使用语言输入，不能据这个实验声称遵循自然语言指令。

SmolVLA 记录来自其训练数据。ACT episode 24 在数据元信息中属于 val，但检查点训练配置 `episodes=null`、未固定数据 revision，无法据 split 标签证明训练没有见过它。两者都仅用作运行检查，不报告留出集性能。两个任务、视图和动作块长度不同，不根据这里的延迟排名判断模型能力。

## 上游来源与许可

- [OPENROB/FURG SmolVLA 检查点](https://huggingface.co/openrob-furg/smolvla-openarm-single-pick-place-lego-n100-targeted50/tree/c6f2e90bee01487c51dd597d2dd100b585354c44)及[配套真实 OpenArm 记录](https://huggingface.co/datasets/openrob-furg/openarm-lego-n100-targeted50/tree/9ea38b57aa9d7c0290f96351a0389bb1fa3f366c)。
- [Enactic ACT 检查点](https://huggingface.co/enactic/act-openarm-2-cell-pick_up_cube_mujoco/tree/27cbd9a205d2e006aef518a54a3c53cf8e421a13)及[配套 MuJoCo 记录](https://huggingface.co/datasets/k1000dai/openarm-2-cell-pick_up_cube_mujoco-lerobot/tree/c37b77992de5004bf0f6f582cbe2e369fc8f9fe4)。
- [SmolVLM2 配置/分词器](https://huggingface.co/HuggingFaceTB/SmolVLM2-500M-Video-Instruct/tree/4cde9d208e19519c36917aa170fffc7e381aa0ad)。
- [LeRobot v0.6.1 源码](https://github.com/huggingface/lerobot/tree/7e241bd630a3719a56157a497ce5d08f244784f1)，实际安装为同版 PyPI 包，完整依赖见 [requirements-lock.txt](requirements-lock.txt)。

以上模型/数据页标注 Apache-2.0，LeRobot 采用 Apache-2.0。下载保留上游 README 与来源；本仓库不重新分发其权重、训练数据或整套源代码。实验脚本仅调用上游公开接口，不主张模型或 OpenArm 机构的原创权。
