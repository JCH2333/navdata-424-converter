import sqlite3

import pytest

from navdata_converter.profile import ProfileError, validate_fenix_profile


def test_profile_rejects_missing_fenix_tables(tmp_path):
    db = tmp_path / "nd.db3"
    sqlite3.connect(db).close()
    with pytest.raises(ProfileError, match="缺少表"):
        validate_fenix_profile(db)
