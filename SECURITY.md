# Security Policy

## Overview

LiteClaw is a local-first desktop agent runtime with a strict security posture:

- No cloud connectivity by default
- No telemetry
- No background network access
- Side-effecting actions require explicit user approval
- Backend-authoritative enforcement of permissions and execution

## Threat Model

LiteClaw assumes the following are in scope:

- Malicious or malformed prompts
- Permission-gating bypass attempts
- Unsafe filesystem access attempts
- Shell command injection attempts
- Approval token replay/reuse attempts
- UI spoofing attempts

Out of scope:

- Compromised host OS
- Malicious user with full local filesystem access
- Kernel/admin-privilege attacks
- Hardware/firmware attacks

LiteClaw does not sandbox the operating system itself.

## Security Design Principles

- Local-only by default
- Deny-by-default permissions
- Backend-authoritative checks
- One-time approval tokens
- Explicit execution plans
- No shell passthrough
- No background execution

All side effects are declared, reviewed, approved, and enforced server-side.

## Reporting a Vulnerability

Do not open a public GitHub issue for security vulnerabilities.

Report privately to: `security@liteclaw.dev` (placeholder; update before public launch)

Please include:

- LiteClaw version
- OS (Windows/macOS/Linux)
- Reproduction steps
- Expected vs actual behavior
- Relevant logs (redacted if needed)

Target response time: acknowledge within 72 hours.

## Supported Versions

| Version | Supported |
| --- | --- |
| v0.1.x (alpha) | Yes |
| < v0.1.0 | No |

## Responsible Disclosure

Please allow a reasonable disclosure window before public release of vulnerabilities.
