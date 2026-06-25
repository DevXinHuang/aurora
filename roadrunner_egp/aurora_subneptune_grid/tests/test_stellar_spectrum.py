from __future__ import annotations

from aurora_grid.stellar_spectrum import _flux_unit, _wavelength_unit


def test_wavelength_unit_aliases():
    from astropy import units as u

    assert _wavelength_unit("AA") == u.AA
    assert _wavelength_unit("angstrom") == u.AA


def test_flux_unit_aliases():
    from astropy import units as u

    assert _flux_unit("erg/(s cm2 AA)") == u.erg / (u.s * u.cm**2 * u.AA)
