# Results

This directory contains results generated for the Gap-Aware REPS project.

## Baseline Reproduction

The `baseline/` directory contains selected plots reproduced from the original
REPS EuroSys 2026 artifact before any Gap-Aware REPS modifications were made.

The original artifact stores generated results under `artifact_results/`, with
each experiment corresponding to a script in `artifact_scripts/`.

For the baseline reproduction, we ran the original `reps_medium.sh` experiment
suite on a CloudLab bare-metal node with:

- Ubuntu 22.04 LTS
- x86_64
- 40 logical CPUs
- 157 GiB RAM
- GCC/G++ 11.4
- Python 3.10

The medium suite completed successfully with:

- Wall-clock time: **1 h 10 min 23 s**
- Peak resident memory: **~4.6 GiB**
- Exit status: **0**

The plots and the raw `artifact_results/fig_*` outputs of the medium run are tracked in Git.

## Instrumentation and cold vs warm start

`instrumentation/` contains the REPS instrumentation experiments (cold vs warm start under
failures, `exit_freeze` sweeps). See `instrumentation/README.md` for findings and reproduction.

## Source

Baseline results were generated from the original REPS artifact:

> Tommaso Bonato et al.,  
> *REPS: Recycled Entropy Packet Spraying for Adaptive Load Balancing and
> Failure Mitigation*, EuroSys 2026.

Upstream artifact:  
https://github.com/tommasobo/REPS_EuroSys_Artifact