---
slug: owner-admin-member-and-analyst-permissions
title: Owner, Admin, Member and Analyst permissions
summary: Understand this workspace setting, access rule, or management workflow.
category: workspace
roles:
- owner
- admin
- member
- analyst
keywords:
- owner
- admin
- member
- and
- analyst
- permissions
- workspace
- team
featured: false
sort_order: 640
---

# Owner, Admin, Member and Analyst permissions

Northstar uses four workspace roles and enforces important permissions in the backend.

## Role overview

- **Owner** — highest workspace management access.
- **Admin** — manages agents, knowledge, integrations, and workspace configuration.
- **Member** — operational write access such as conversations/leads where allowed.
- **Analyst** — primarily read/analytics-oriented access.

## Important examples

- Agents and Knowledge management: Owner/Admin.
- Conversation and Lead write operations: Owner/Admin/Member.
- Analytics reading: all authenticated roles.
- Integrations and Workspace management: Owner/Admin.

## Security

The frontend can hide or disable controls, but the backend authorization dependency is the real enforcement boundary.

## Troubleshooting

If you need a restricted action, ask a workspace Owner/Admin to perform it or change your role through the normal team-management process.
