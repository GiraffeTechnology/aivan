# AIVAN Stage B1-A rollback boundary

Rollback is commit-based. It must not use force-push, history rewriting, schema
changes, service reconfiguration, or a deployment shortcut.

1. Stop promotion of the B1-A candidate. This work does not authorize merge or
   deployment.
2. If audit or required checks fail after merge, create a reviewed `git revert`
   of the accepted B1-A commit; never reset or rewrite `main`.
3. Confirm that the revert touches only the B1-A application, documentation,
   configuration-schema, CI typing list, and test files. Do not modify DB,
   giraffe-db, GLTG, GPM, MyAivan, migrations, or servers.
4. Rerun the original six B1-A nodeids and all PR #77 audit regression nodeids,
   then full pytest, Ruff, Mypy, Bandit, module budget, and Stage 6 five-pass
   preflight on the revert candidate.
5. Submit the revert head/tree and evidence to the audit owner. The coding owner
   must not self-merge.

Rollback restores configuration-only readiness and permits critical business
mutations without a real dependency probe. It also removes tenant-bound DB
probe authentication, shared-endpoint health enforcement, the complete
mutation inventory and bounded parallel fan-out. Therefore a reverted build is
not a production-safe acceptance path and must remain blocked from deployment
until an independently accepted replacement exists.
