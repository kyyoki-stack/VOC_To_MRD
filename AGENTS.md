# VOC_To_MRD collaboration rules

- This is a standalone website project. Read README.md and docs/architecture.md before changing the research pipeline.
- Keep source material and research interpretation separate. Quotes, counts and evidence IDs must be traceable; no invented comments or inferred identities.
- The anonymous cockpit example is an existing research snapshot. Never reuse it as if it were newly collected for another topic.
- New research goes into an isolated research-runs/<id>/ directory, with Markdown documents under docs/ and CSV data under data/. These runs are ignored by Git.
- Preserve existing research inputs. Generate the example page with python3 build.py; check with python3 build.py --check.
- Data report precedes MRD. BRD and PRD are produced only when explicitly requested and must inherit earlier evidence.
- Never publish authentication, browser profiles, execution logs, local user paths or research runs. Publishing new research requires the user's authorization.
