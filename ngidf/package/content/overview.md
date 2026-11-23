<!-- Section 1 of the QC package (ngidf/package/build.py). Plain language, no results: the results of
     a run are in section 3. The six steps and the flowchart are drawn from STEPS in build.py.
     {{name}} placeholders are filled from the run (build.py facts()): durations, return_periods. -->

## What this is for

Engineers size culverts, ditches and storm drains for a design storm, such as "the most rain expected in
24 hours once in 100 years". These numbers come from intensity-duration-frequency (IDF) curves, which
are usually built from precipitation alone. In cold regions, the water that floods a culvert is
not only rain: snowmelt adds to it, sometimes on the same day as the rain (rain-on-snow), and part of
the snowfall stays on the ground for weeks before melting. **Next-generation IDF (NG-IDF)** curves
account for this. They describe the water that actually reaches the ground surface due to rain plus snowmelt.
They can be larger or smaller than precipitation IDF curves.

H. Yan and colleagues at Pacific Northwest National Laboratory (PNNL) built the **NG-IDF app**, which
computes these curves for a single point. It simulates the snowpack and the water reaching the ground
hour by hour with the DHSVM hydrology model, and takes the largest amount in each year for each
duration ({{durations}}). It then fits a statistical curve to those yearly maxima to estimate the events
that recur on average every {{return_periods}} years.

## What SNAP does with it

SNAP runs the author's application for Alaska communities in its place list, with several
climate datasets: an observation-based historical record (Daymet) and regional climate model
simulations of the past and the future (WRF and CESM). The result is a set of NG-IDF curves for each
place and dataset, designed to be served through SNAP's data API and used in community reports.

Running one app many times instead of once by hand needs a few things the app does not provide: a
description of the ground at each place, weather series in the app's format for each place and dataset,
and a way to run thousands of copies on a computing cluster. Those are the steps below. Each step checks
its own results before the next one starts, and section 3 reports those checks for this run.

The description of the ground has three parts: the land cover, the leaf area index (LAI) and the canopy
height. In the app these are **defaults**: when a point is clicked, the web page fills them in, and the
user can change them. They come from the 1 km grid cell nearest the point, called the **defaults cell**
in this document. The weather comes separately, from the nearest cell of each climate dataset, so one
place uses different cells for its ground description and for its weather ([Appendix A.1](#in-places)).

## How to read this document

- **Section 2** says exactly what was run: the model version, the code version, and the settings of
  this run.
- **Section 3** gives the results of every check, step by step, and an overview of the curves.
- **Section 4** lists the known issues: places where the results have limits or more work is planned.
- **The appendices** describe every input and how it was prepared, the method settings read from the
  author's code, and the record needed to reproduce the run.
