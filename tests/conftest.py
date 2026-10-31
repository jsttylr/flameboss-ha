import pathlib

import custom_components
import pytest

# Make sure HA finds this repo's integration even if the test harness's own
# custom_components package was imported first.
_ours = str(pathlib.Path(__file__).resolve().parent.parent / "custom_components")
if _ours not in list(custom_components.__path__):
    custom_components.__path__.insert(0, _ours)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
