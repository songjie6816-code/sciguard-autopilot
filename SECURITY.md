# Security Policy

## Reporting a vulnerability

Please do not disclose an exploitable vulnerability in a public issue. Use GitHub's private vulnerability reporting for this repository when available, or contact the repository owner through the profile listed on GitHub.

Include the affected revision, reproduction steps, impact, and whether the issue can alter policy, approvals, evidence receipts, or DataHub write-back. Do not include real credentials or confidential scientific data.

## Supported version

The latest release and the default branch receive security fixes. The hackathon reference release `v1.0.0-hackathon` is immutable; a material fix will be published as a new version with an explicit evidence boundary.

## Security boundary

SciGuard is a research prototype, not a production authorization system. The public edge sandbox accepts no arbitrary repositories or scenarios and performs no anonymous GitHub or production DataHub mutations. Demo-signed approval is not enterprise SSO/OIDC, and synthetic-staging application is not production deployment.
