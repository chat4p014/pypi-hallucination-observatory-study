# Measuring the Lifecycle of Hallucinated Packages on PyPI

Code and data reproducing an Applied Observational Study (Edgar & Manz,
2017) of the lifecycle of package names hallucinated by large language
models on the Python Package Index.

## Layout

    src/          9-step pipeline (numbered in run order)
      plot/       Plotting scripts
    data/         Input and intermediate CSV
      watchlist_scans/   First and last snapshots from phase 3
    results/      Correlation JSON and figures
      figures/    PNG outputs

## Install

    pip install -r requirements.txt

Requires Python >= 3.10.

## Pipeline

Network-facing steps (03, 05, 06, 07) read public metadata only, cap at
2 QPS, and identify themselves with an academic User-Agent. No wheel or
sdist is ever installed; step 07 downloads archives for static analysis
but never executes their code.

    # 1. Build the candidate list (~2033 packages)
    python src/01_build_candidates.py \
        --seed-csv data/seed_incidents.csv \
        --output   data/candidates.csv

    # 2. Filter legitimate overlap (~1869 remaining)
    python src/02_filter_candidates.py \
        --input  data/candidates.csv \
        --output data/candidates_filtered.csv \
        --top-n 10000

    # 3. Passive PyPI metadata monitoring (repeat every 4h via cron)
    cut -d, -f1 data/candidates_filtered.csv | tail -n +2 > /tmp/names.txt
    python src/03_monitor_pypi.py /tmp/names.txt \
        data/watchlist_scans/scan_$(date +%Y%m%d_%H%M%S).csv

    # 4. Extract PyPI advisories from the OSSF repository (11233 records)
    #    git clone --depth 1 https://github.com/ossf/malicious-packages.git \
    #        data/ossf_raw
    python src/04_extract_ossf.py \
        --input  data/ossf_raw/osv/malicious/pypi \
        --output data/ossf_advisories.csv

    # 5. Enrich each advisory with current PyPI status
    python src/05_enrich_ossf.py \
        --input  data/ossf_advisories.csv \
        --output data/ossf_enriched.csv

    # 6. Enrich with download counts (pypistats.org)
    python src/06_enrich_downloads.py \
        --output data/downloads.csv \
        --from-csv-alive "ossf_alive:data/ossf_alive.csv"

    # 7. Static analysis of the 64 OSSF packages still alive
    python src/07_static_analysis.py \
        --input        data/ossf_alive.csv \
        --output       data/ossf_static_auto.csv \
        --details-dir  data/static_details \
        --workdir      /tmp/static_workdir \
        --cleanup

    # 8. Merge automatic labels with manual overrides
    python src/08_classify.py \
        --auto-classification data/ossf_static_auto.csv \
        --downloads           data/downloads.csv \
        --manual              data/manual_review.csv \
        --output              data/ossf_classification.csv

    # 9. Spearman correlation between releases and downloads
    python src/09_correlation.py \
        --watchlist-dir data/watchlist_scans \
        --downloads     data/downloads.csv \
        --output        results/correlation.json

Plots:

    python src/plot/plot_alive_age_hist.py \
        --scan       data/watchlist_scans/scan_20260620_012414.csv \
        --candidates data/candidates.csv \
        --output     results/figures/alive_age_hist.png

    python src/plot/plot_ossf_classification.py \
        --classification data/ossf_classification.csv \
        --output         results/figures/ossf_classification.png

    python src/plot/plot_spearman_scatter.py \
        --watchlist-dir data/watchlist_scans \
        --downloads     data/downloads.csv \
        --output        results/figures/spearman_scatter.png

## Headline numbers

Computed from the CSVs in `data/`:

  - Candidate pool: 2033 packages (34 disclosed-incident seeds + 2000
    generated from the Spracklen patterns; one dropped as a duplicate
    normalized name).
  - After filtering: 1869 packages for long-term monitoring. 188 were
    still alive on the final phase-1 scan; the phase-3 watchlist is a
    union of two sources — 27 packages that survived phase 2 plus 44
    packages taken from OSSF advisories still returning HTTP 200 and
    from public disclosure reports (huggingface-cli, arangopipe,
    requests3, ...) — for a total of 71 packages monitored closely.
  - OSSF PyPI advisories: 11233 records. 64 packages still responded
    with HTTP 200 during the study period; static analysis and manual
    review confirmed 10 (0.089%) as actively malicious.
  - True positive rate after manual verification: 7 / 2033 = 0.34%,
    roughly 58x smaller than the 19.7% package hallucination rate
    reported by Spracklen et al.
  - Spearman correlation between release count and last-month
    downloads, restricted to the 18 watchlist packages with downloads
    > 0: rho = 0.80, p < 0.001, 95% CI [0.469, 0.970].

Observation window: approximately 24 continuous days — phase 1 ran for
about 36 hours with 8 scans over 2033 candidates; phase 3 ran for about
20 days with 122 scans on 4-hour intervals over the 71-package
watchlist.

## Ethical constraints

  - No package code is ever executed. Step 07 only walks the AST.
  - `pip download` is avoided: pip still runs `setup.py egg_info`.
  - Rate limits stay at or below 2 QPS with a public User-Agent.
  - Newly identified malicious packages have not been reported to the
    Python Software Foundation during the study period; disclosure is
    planned only after the study concludes.

## Data sources

  - PyPI JSON API — <https://docs.pypi.org/api/json/>
  - pypistats.org — <https://pypistats.org/api/>
  - OSSF Malicious Packages —
    <https://github.com/ossf/malicious-packages>
  - Top-PyPI list — <https://hugovk.github.io/top-pypi-packages/>

## References

Edgar, T. W., & Manz, D. O. (2017). *Research Methods for Cyber
Security.* Syngress. Chapter 12.

Spracklen, J., et al. (2025). *We Have a Package for You: A Comprehensive
Analysis of Package Hallucinations by Code Generating LLMs.* USENIX
Security Symposium.
