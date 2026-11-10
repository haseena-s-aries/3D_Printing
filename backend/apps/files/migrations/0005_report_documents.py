"""CN-005 report builder: supporting-document classes, per-document client visibility and PDF page counts.

Existing documents keep the visibility they had (added with True); new documents start hidden (default then False).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('files', '0004_photos_and_thumbnails'),
    ]

    operations = [
        migrations.AddField(
            model_name='engineeringfile',
            name='client_visible',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='engineeringfile',
            name='client_visible',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='fileversion',
            name='page_count',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='engineeringfile',
            name='category',
            field=models.CharField(choices=[('3d_model', 'Interactive 3D model'), ('drawing', 'Engineering drawing'), ('specification', 'Manufacturing specification'), ('inspection', 'Inspection and quality'), ('certificate', 'Certification'), ('photo', 'Photographs'), ('other', 'Other'), ('mat_cert', 'Material certificate'), ('mech_test', 'Mechanical test report'), ('chem_analysis', 'Chemical analysis report'), ('lab_test', 'Laboratory test report')], default='other', max_length=16),
        ),
    ]
