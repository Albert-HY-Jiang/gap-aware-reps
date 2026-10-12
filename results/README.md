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

Only selected plots are tracked in Git. Large raw simulator outputs and
intermediate files are not committed to the repository.

## Source

Baseline results were generated from the original REPS artifact:

> Tommaso Bonato et al.,  
> *REPS: Recycled Entropy Packet Spraying for Adaptive Load Balancing and
> Failure Mitigation*, EuroSys 2026.

Upstream artifact:  
https://github.com/tommasobo/REPS_EuroSys_Artifact