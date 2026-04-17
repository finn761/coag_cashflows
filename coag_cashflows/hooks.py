app_name = "coag_cashflows"
app_title = "COAG Cashflows"
app_publisher = "Camden Open Air Gallery"
app_description = "Cashflows IPP payment integration for ERPNext POS Next"
app_email = "tech@camdenopenairgallery.com"
app_license = "MIT"

# Fixtures
# --------
# Custom fields on POS Profile and POS Invoice are exported as fixtures so that
# `bench --site <site> install-app coag_cashflows` (or `bench migrate`) applies
# them idempotently. They are filtered by the fieldname prefix `custom_cashflows_`.
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["fieldname", "like", "custom_cashflows_%"],
        ],
    },
]

# Installation
# ------------
after_install = "coag_cashflows.install.after_install"
after_migrate = "coag_cashflows.install.after_migrate"
