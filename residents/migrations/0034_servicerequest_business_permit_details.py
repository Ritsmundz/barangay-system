from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("residents", "0033_servicerequest_date_of_death_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="business_activity_type",
            field=models.CharField(blank=True, choices=[("main_office", "Main Office"), ("branch", "Branch"), ("admin_office_only", "Admin Office Only")], max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_area_sqm",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_block_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_building_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_capital_investment",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_corporation_nationality",
            field=models.CharField(blank=True, choices=[("filipino", "Filipino"), ("foreign", "Foreign")], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_delivery_motorcycles",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_delivery_vans",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_email",
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_equipment",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_equipment_size",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_equipment_units",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_female_employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_floor_area_sqm",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_has_tax_incentives",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_house_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_lot_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_male_employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_occupancy_type",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_occupants",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_operation_time",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_organization_type",
            field=models.CharField(blank=True, choices=[("sole_proprietorship", "Sole Proprietorship"), ("partnership", "Partnership"), ("corporation", "Corporation"), ("cooperative", "Cooperative")], max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_president_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_products_services",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_property_identification_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_property_status",
            field=models.CharField(blank=True, choices=[("owned", "Owned"), ("leased", "Leased")], max_length=20, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_psic_code",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_qc_employee_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_registration_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_representative_designation",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_storeys",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_street",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_subdivision",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_tax_declaration_number",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_telephone",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_tin",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_trade_name",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="business_zip_code",
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
