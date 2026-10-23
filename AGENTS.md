# Working on Cadenza Robotics

- Read README.md, BUILD.md and BASELINES.md before proposing a new direction. Current scope is a fixed-table bimanual OpenArm platform with grippers: bring up each arm, collect demonstrations, then reproduce autonomous flat-shirt folding before crumpled-shirt folding. Use the public LeRobot folding work as a reference, subject to hardware and interface compatibility checks. Dexterous hands and piano are deferred.
- Understand the existing design, source code and evidence before choosing or modifying a method. Explain the observed failure, the change and how it will be measured.
- Preserve OpenArm load-bearing structure, joint geometry, transmission and mechanical limits in the initial platform. Custom shells are removable, non-load-bearing parts. Check their mass, clearance, heat, wiring, camera view and maintenance access.
- Distinguish author results, company reports, simulation, motion previews and our measured hardware results. Files present on disk do not prove that hardware exists or that a system has been reproduced.
- Record immutable source revisions and meaningful hardware/firmware/configuration changes. Do not invent measurements, ownership, costs or compatibility.
- Paper notes, PDFs, images and video links belong in Jeffaaay/robotics-research-notes, one folder per paper. Link them here rather than duplicating notes, indexes or summaries.
- Keep project files few and purposeful. Create code, configurations and design directories only when they contain useful work. Do not copy whole upstream repos, environments, raw datasets or media into Git.
- Keep current plans in README.md, assembly details in BUILD.md and evaluation definitions in BASELINES.md. Update existing sections instead of accumulating competing plans.
- Changes to source or docs do not authorize purchasing, installation, motor activation or physical actuation. Follow explicit session authorization; do not add approval requests for already-authorized routine repository work.
- Preserve upstream attribution and license notices. Cadenza is our integration and research project, not a claim that the underlying OpenArm mechanism is original.
- For comparisons, preserve a runnable original baseline and record all failed, aborted and successful trials. Match tasks, hardware, calibration budget and observation conditions.
