import frappe


def create_workstation():
    WS_SLADE_ID = "731ddef2-9011-4fbe-8f15-af86a81e9bd7"
    existing = frappe.db.get_value(
        "Navari KRA eTims Workstation", {"slade_id": WS_SLADE_ID}, "name"
    )
    if existing:
        print(f"Workstation already exists: {existing}")
        return existing
    ws = frappe.get_doc({
        "doctype": "Navari KRA eTims Workstation",
        "slade_id": WS_SLADE_ID,
    })
    ws.insert(ignore_permissions=True)
    frappe.db.commit()
    print(f"Workstation created: {ws.name}")
    return ws.name
