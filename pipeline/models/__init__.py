"""Model map pipeline (Phase 2): HRRR / RRFS / GFS GRIB2 from NOAA Open Data
Dissemination on AWS via Herbie byte-range requests -> static PNG maps +
index JSON for web/models.html.

    python -m pipeline models --model hrrr [--fhours 0 6 12] [--domains west wasatch]

Modules: config (yaml + pure expansion), fetch (network + ecCodes decode),
derive (pure meteorology), plot (Cartopy/Matplotlib rendering), run
(orchestration), catalog (site-wide index).
"""
