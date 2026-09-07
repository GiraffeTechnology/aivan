# G2-A remediation rollback

Rollback is commit-based and must not use force-push or history rewriting.

1. Stop promotion of the candidate; no deployment is authorized by this work.
2. Revert the remediation commit with a new `git revert` commit if independent audit or required CI fails.
3. Confirm the revert restores the audited PR #76 tree behavior without modifying giraffe-db, schemas, or migrations.
4. Rerun focused GPM tests, full pytest, static gates, and Stage6 five-pass evidence on the revert candidate.
5. Submit the revert candidate to the audit owner; the coding owner must not self-merge.

Operational consequence: rollback restores tenant-only HMAC decision behavior and the other audited defects, so the reverted candidate remains forbidden from merge or deployment. Rollback is only a recovery mechanism, not an acceptance path.
