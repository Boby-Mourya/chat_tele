---
slug: session-and-authentication-basics
title: Session and authentication basics
summary: Use this security/privacy control without weakening existing protections.
category: security
roles:
- owner
- admin
- member
- analyst
keywords:
- session
- and
- authentication
- basics
- privacy
- security
featured: false
sort_order: 790
---

# Session and authentication basics

Northstar uses authenticated sessions/tokens to determine the current user, workspace, and role before protected API operations.

## Before you start

This guide is available to all authenticated workspace roles.

## What happens

The frontend API layer sends authenticated requests and has an access-token refresh path. Backend dependencies resolve the current principal and tenant context before protected routes run.

## Security basics

- Do not share access or refresh tokens.
- Sign out on shared devices.
- Re-authenticate when the session expires.
- Treat repeated unexpected authentication failures as a security/support issue rather than bypassing the checks.

## Troubleshooting

If your session expired, sign in again. If the problem continues, use **Help → Troubleshooting → I cannot sign in**.
