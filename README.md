# MinisSkills

Reusable skills for [Open Minis](https://openminis.app/) / Minis agent workflows.

## Skills

| Skill | Description |
|---|---|
| [`image-generator`](./image-generator/) | Generate or edit images through OpenMinis `minis-model-use`, with WisArt parameters and recovery guidance. |
| [`github-sync-helper`](./github-sync-helper/) | Safe Git/GitHub workflows for repositories, PRs, Issues, Releases and Actions. |
| [`cloudflare-dns`](./cloudflare-dns/) | Manage and verify Cloudflare DNS records with `flarectl`. |
| [`self-improving-agent`](./self-improving-agent/) | Structured reusable learning/error/feature logging workflows; runtime logs are excluded. |
| [`skill-creator`](./skill-creator/) | Guidance for designing and validating Minis skills. |
| [`unrestricted`](./unrestricted/) | Direct cooperation style and broad technical/creative routing instructions. |

Private standalone skills such as `blackforge-reverse-lab` and `juyue-rule-dev` are intentionally not included in this public repository.

## Install

See the complete [Minis skill installation guide](./INSTALL.md).

Copy a skill directory into your Minis skills folder:

```text
/var/minis/skills/<skill-name>/
```

Each skill follows the `SKILL.md` convention.
