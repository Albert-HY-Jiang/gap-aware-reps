# Gap-Aware REPS

This repository extends the artifact accompanying:

**REPS: Recycled Entropy Packet Spraying for Adaptive Load Balancing and Failure Mitigation**  
Tommaso Bonato et al., EuroSys 2026.

Original artifact:
https://github.com/tommasobo/REPS_EuroSys_Artifact

This fork is being developed as part of an ECE 509 course project at the
University of Illinois Urbana-Champaign. The project investigates how REPS
path-selection state behaves across idle intervals between recurring AI
collective communication rounds, and explores gap-aware reuse of previously
learned entropy values (EVs).

## Project Status

The current work builds on the original REPS implementation and evaluation
framework. Planned modifications include:

- instrumentation of REPS path-selection and cache state;
- characterization of REPS behavior before and after idle periods;
- measurement of cached-path freshness across communication gaps;
- simulation of recurring AI collective workloads with compute gaps; and
- evaluation of gap-aware path reuse and re-exploration policies.

The original REPS implementation and artifact remain the baseline for this
work.

## Upstream

This repository is derived from:

> Tommaso Bonato et al.,  
> *REPS: Recycled Entropy Packet Spraying for Adaptive Load Balancing and
> Failure Mitigation*, EuroSys 2026.

Upstream repository:  
https://github.com/tommasobo/REPS_EuroSys_Artifact

Changes specific to this project are maintained separately from the upstream
implementation.

## License

This repository retains the original **BSD 2-Clause License** and copyright
notice.

Copyright (c) 2025 Ultra Ethernet Consortium

See [`LICENSE`](LICENSE) for the complete license text.

Unless otherwise noted, modifications in this repository are distributed
under the same BSD 2-Clause License.