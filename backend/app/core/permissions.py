ALL = {
    "documents:read", "documents:upload", "documents:delete", "documents:process",
    "invoices:read", "invoices:edit", "invoices:verify",
    "transactions:read", "transactions:import",
    "reconciliation:read", "reconciliation:write",
    "duplicates:read", "duplicates:review",
    "exports:read", "exports:create", "dashboard:read", "audit:read",
    "members:manage", "settings:manage",
}
READ = {"documents:read", "invoices:read", "transactions:read", "reconciliation:read",
        "duplicates:read", "dashboard:read"}

ROLES = ("ADMIN", "ACCOUNTANT", "CONTRIBUTOR", "VIEWER")

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "ADMIN": set(ALL),
    "ACCOUNTANT": ALL - {"members:manage", "settings:manage"},
    "CONTRIBUTOR": READ | {"documents:upload", "documents:process", "invoices:edit"},
    "VIEWER": set(READ),
}
