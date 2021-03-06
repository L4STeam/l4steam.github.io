This repository hosts various resources about L4S, and the existing implementations.

See the general [L4S Landing Page](https://riteproject.eu/dctth) for various resources around L4S.

# Components

All various components required to test L4S are under a [common Github umbrella](https://github.com/L4Steam). In particular:
- [Linux kernel](https://github.com/L4Steam/linux) containing the necessary patches
enabling TCP prague and the dualpi2 qdisc. The repository also provides
pre-packaged debian binaries to ease up experimentation.
- [iproute2](https://github.com/L4steam/iproute2) user-space utilities to manage
the dualpi2 qdisc and query the TCP Prague statistics.
- [GUI (l4sdemo)](https://github.com/L4steam/l4sdemo) that enables to dynamically interact with a testbed,
visualising per-packet latencies, ... as well as support script to automate more
in-depth testing.
- [l4steam.github.io](https://github.com/L4STeam/l4steam.github.io), the [web interface](https://l4steam.github.io/) for this repository with links to main components, current status (Feb 2021) of Prague implementations and experiments.
- [SCReAM](https://github.com/L4Steam/scream), a mobile optimized congestion control algorithm which supports L4S.

# Prague requirements Compliance

The IETF [draft-ietf-tsvwg-ecn-l4s-id](https://datatracker.ietf.org/doc/draft-ietf-tsvwg-ecn-l4s-id/) contains a list of requirements an L4S congestion control should comply with. The following template document provides a checklist to the different normative paragraphs listed in [draft-ietf-tsvwg-ecn-l4s-id-12](https://datatracker.ietf.org/doc/html/draft-ietf-tsvwg-ecn-l4s-id-12):
- [Template_L4S_requirements_Compliance_and_Objections.docx](https://l4steam.github.io/PragueReqs/Template_L4S_requirements_Compliance_and_Objections.docx)   [pdf](https://l4steam.github.io/PragueReqs/Template_L4S_requirements_Compliance_and_Objections.pdf)

This list of requirements is still being discussed and finetuned. Consensus on feasibility, performance and usefulness needs to be reached. The following contributions, grouped in (partial) available implementations and potential/planned implementations will be taken into account for that purpose.

Currently existing implementations:
- Linux TCP-Prague by L4Steam (this git): [Linux_TCP_Prague_L4S_requirements_Compliance_and_Objections pdf](https://l4steam.github.io/PragueReqs/Linux_TCP_Prague_L4S_requirements_Compliance_and_Objections.pdf)   [docx](https://l4steam.github.io/PragueReqs/Linux_TCP_Prague_L4S_requirements_Compliance_and_Objections.docx)
- SCReAM by Ingemar Johansson (RFC8298 std + [running code](https://github.com/L4Steam/scream)): [Scream_L4S_requirements_Compliance_and_Objections pdf](https://l4steam.github.io/PragueReqs/Scream_L4S_requirements_Compliance_and_Objections.pdf)   [docx](https://l4steam.github.io/PragueReqs/Scream_L4S_requirements_Compliance_and_Objections.docx)
- GeforceNow by NVIDIA: [GeforceNow_L4S_requirements_Compliance_and_Objections pdf](https://l4steam.github.io/PragueReqs/GeforceNow_L4S_requirements_Compliance_and_Objections.pdf)   [docx](https://l4steam.github.io/PragueReqs/GeforceNow_L4S_requirements_Compliance_and_Objections.docx)
- ...

Planned/potential implementations:
- ...

Consolidated view including private contributions: [Prague_requirements_consolidated.pdf](https://l4steam.github.io/PragueReqs/Prague_requirements_consolidated.pdf)

# Experiments

[TCP Prague controlled RTT dependence](rtt-independence)

[ECT(1) tests](ect1-tests)

[DualPI2 overload experiments](overload-experiments)

[ICCRG experiments (21/11/2020)](iccrg-exp)
