"""add file size field

Revision ID: 30bfe33aa328
Revises: 5cee97aab219
Create Date: 2022-12-13 22:32:12.242394

"""

# revision identifiers, used by Alembic.
revision = '30bfe33aa328'
down_revision = '5cee97aab219'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session
from flask import current_app
from pathlib import Path

Base = automap_base()

def upgrade():
    op.add_column('file', sa.Column('size', sa.BigInteger(), nullable=True))
    bind = op.get_bind()
    Base.prepare(autoload_with=bind)
    File = Base.classes.file
    session = Session(bind=bind)

    storage = Path(current_app.config["FHOST_STORAGE_PATH"])

    updates = []
    files = session.scalars(sa.select(File).where(sa.not_(File.removed)))
    for f in files:
        p = storage / f.sha256
        if p.is_file():
            updates.append({
                "id" : f.id,
                "size" : p.stat().st_size
            })

    session.bulk_update_mappings(File, updates)
    session.commit()


def downgrade():
    op.drop_column('file', 'size')
