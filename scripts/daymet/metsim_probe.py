"""Reverse-engineer the author's Daymet→MetSim 3-hourly forcing for one cell.

Builds MetSim inputs from the Daymet v4 single-pixel CSV (prcp, tmax, tmin) and
daily WRF wind (daily mean of the author's hourly WRF file over 01-00 UTC = 16-15
local), runs MetSim with the options given, and compares with the author's
NG-IDL/dhsvm_daymet_3hour file.

Usage: metsim_probe.py <daymet_key> <wrf_key> <workdir> <start> <stop> [key=value MetSim options...]
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

key, wrf_key, work, start, stop = sys.argv[1:6]
opts = dict(a.split('=', 1) for a in sys.argv[6:])
elev = float(opts.pop('elev', 'nan'))
dec31 = opts.pop('dec31', 'mean')  # how to fill the leap-year Dec 31 Daymet omits: prev | next | mean
work = Path(work); work.mkdir(parents=True, exist_ok=True)
DATA = Path('/import/beegfs/SNAP/jdpaul3/ng-idf_curation_data')
NGIDL = Path('/import/beegfs/CMIP6/arctic-cmip6/NG-IDL')
lat, lon = map(float, key.split('_'))

raw = (DATA / f'raw/daymet_v4_pixels/pix_{key}.csv').read_text().splitlines()
hdr_elev = float([l for l in raw if l.startswith('Elevation')][0].split()[1])
if not np.isfinite(elev):
    elev = hdr_elev
dm = pd.read_csv(DATA / f'raw/daymet_v4_pixels/pix_{key}.csv', skiprows=6)
dm.columns = ['year', 'yday', 'dayl', 'prcp', 'srad', 'swe', 'tmax', 'tmin', 'vp']
dm['date'] = pd.to_datetime(dm.year.astype(str)) + pd.to_timedelta(dm.yday - 1, unit='D')
dm = dm.set_index('date')
# Daymet drops Dec 31 in leap years: fill it (P = 0, T from Dec 30)
full = pd.date_range(dm.index.min(), dm.index.max() + pd.Timedelta(days=1), freq='D')
dm = dm.reindex(full)
miss = dm.prcp.isna()
dm.loc[miss, 'prcp'] = 0.0
if dec31 == 'prev':
    dm[['tmax', 'tmin']] = dm[['tmax', 'tmin']].ffill()
elif dec31 == 'next':
    dm[['tmax', 'tmin']] = dm[['tmax', 'tmin']].bfill()
else:
    dm[['tmax', 'tmin']] = dm[['tmax', 'tmin']].interpolate()

w = pd.read_csv(NGIDL / f'dhsvm_wrf_1hour/hist/data_{wrf_key}', sep=r'\s+', header=None,
                names=['t', 'T', 'W', 'RH', 'SW', 'LW', 'P'], usecols=[0, 2])
w['ts'] = pd.to_datetime(w.t, format='%m/%d/%Y-%H')
# WRF daily file D covers UTC D 01:00 .. D+1 00:00 = local D-1 16:00 .. D 15:00
w['day'] = (w.ts + pd.Timedelta(hours=9) - pd.Timedelta(hours=1)).dt.normalize()
wind = w.groupby('day').W.mean()
dm['wind'] = wind.reindex(dm.index)

t0, t1 = pd.Timestamp(start), pd.Timestamp(stop)
state_days = pd.date_range(t0 - pd.Timedelta(days=90), t0 - pd.Timedelta(days=1), freq='D')
def ds_for(idx, with_wind):
    d = dm.loc[idx]
    v = {'prec': d.prcp, 't_max': d.tmax, 't_min': d.tmin}
    if with_wind:
        v['wind'] = d.wind.fillna(d.wind.mean())
    return xr.Dataset({k: (('time', 'lat', 'lon'), s.values.reshape(-1, 1, 1).astype('f8')) for k, s in v.items()},
                      coords={'time': idx, 'lat': [lat], 'lon': [lon]})
ds_for(pd.date_range(t0, t1, freq='D'), True).to_netcdf(work / 'forcing.nc')
ds_for(state_days, False).to_netcdf(work / 'state.nc')
xr.Dataset({'elev': (('lat', 'lon'), [[elev]]), 'mask': (('lat', 'lon'), [[1]])},
           coords={'lat': [lat], 'lon': [lon]}).to_netcdf(work / 'domain.nc')

from metsim import MetSim
params = dict(time_step='180', start=start, stop=stop, forcing=str(work / 'forcing.nc'),
              domain=str(work / 'domain.nc'), state=str(work / 'state.nc'), forcing_fmt='netcdf',
              out_dir=str(work / 'out'), out_prefix='ms', scheduler='threading', prec_type='uniform',
              forcing_vars={'prec': 'prec', 't_max': 't_max', 't_min': 't_min', 'wind': 'wind'},
              state_vars={'prec': 'prec', 't_max': 't_max', 't_min': 't_min'},
              domain_vars={'lat': 'lat', 'lon': 'lon', 'mask': 'mask', 'elev': 'elev'},
              out_vars={'temp': {'out_name': 'temp'}, 'prec': {'out_name': 'prec'},
                        'shortwave': {'out_name': 'shortwave'}, 'longwave': {'out_name': 'longwave'},
                        'rel_humid': {'out_name': 'rel_humid'}, 'wind': {'out_name': 'wind'},
                        'vapor_pressure': {'out_name': 'vapor_pressure'}},
              chunks={'lat': 1, 'lon': 1})
for k, v in opts.items():
    params[k] = {'True': True, 'False': False}.get(v, v)
(work / 'out').mkdir(exist_ok=True)
ms = MetSim(params)
ms.run()
o = xr.open_mfdataset(str(work / 'out/*.nc')).isel(lat=0, lon=0).to_dataframe()
a = pd.read_csv(NGIDL / f'dhsvm_daymet_3hour/data_{key}', sep=r'\s+', header=None,
                names=['t', 'T', 'W', 'RH', 'SW', 'LW', 'P'])
a['time'] = pd.to_datetime(a.t, format='%m/%d/%Y-%H')
m = a.merge(o.reset_index(), on='time')
# The author's RH: MetSim vapour pressure (kPa) with Bolton saturation (as in his WRF files), capped at 99.99
m['rh_bolton'] = np.minimum(100 * m.vapor_pressure * 1000 / (611.2 * np.exp(17.67 * m.temp / (m.temp + 243.5))), 99.99)
print(f'opts={opts} dec31={dec31} elev={elev} (daymet hdr {hdr_elev}) n={len(m)}')
for ours, ref in [('temp', 'T'), ('wind', 'W'), ('rel_humid', 'RH'), ('rh_bolton', 'RH'), ('shortwave', 'SW'), ('longwave', 'LW')]:
    d = m[ours] - m[ref]
    print(f'  {ref:3s} maxabs {d.abs().max():9.4f} meanabs {d.abs().mean():8.4f} bias {d.mean():+8.4f}')
d = m.prec / 1000 - m.P
print(f'  P   maxabs {d.abs().max():.2e}')
print(m[['t', 'T', 'temp', 'RH', 'rel_humid', 'SW', 'shortwave', 'LW', 'longwave']].head(8).round(3).to_string())
m['month'] = m.time.dt.month
m['dRH'] = m.rh_bolton - m.RH
m['dT'] = m.temp - m['T']
m['dLW'] = m.longwave - m.LW
print(m.groupby('month')[['dRH', 'dT', 'dLW']].agg(lambda x: x.abs().mean()).round(3).T.to_string())
print(m.loc[m.dT.abs() > 0.01, ['t', 'T', 'temp']].head(10).to_string())
print(m.loc[m.dRH.abs() > 5, ['t', 'T', 'RH', 'rel_humid', 'P']].head(10).to_string())
m.to_csv(work / 'compare.csv', index=False)
