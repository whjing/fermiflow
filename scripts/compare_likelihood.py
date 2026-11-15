#%%
# models = {
#     "Point": -3401447.786,
#     "Disk": -3401458.283,
#     "Gaussian": -3401459.025,
# }
# models = {
#     "Point": -3401446.732,
#     "Disk": -3401457.140,
#     "Gaussian": -3401457.872,
# }
# point_logl = models["Point"]
models = {
    "Point": -3401458.04,
    "Disk": -3401457.140,
    "Gaussian": -3401457.872,
}
point_logl = models["Point"]
models = {
    "Point":   -3401458.04,
    "Disk": -3401458.283,
    "Gaussian":  -3401459.025
}
point_logl = models["Point"]
# models = {
#     "PL": -3401460.639,
#     "LogParabola": -3401460.644,
# }
# point_logl = models["PL"]
models = {
    "PL":  -37170737.974,
    "LogParabola": -37170739.695,
}
point_logl = models["PL"]

# models = {
#     "Point": -3401458.04,
#     "0.10": -3401459.448,
#     "0.15": -3401459.747,
#     "0.20": -3401459.838,
#     "0.25": -3401459.747,
#     "0.30": -3401459.442,
#     "0.336": -3401459.025,
# }

# ref = models["Point"]
ref = point_logl
print(f"{'Model':<10} {'logL':>15} {'TS_ext':>20}")
print("-" * 48)

for name, neg_logl in models.items():
    ts_ext = 2 * (ref - neg_logl)
    print(f"{name:<10} {neg_logl:>15.3f} {ts_ext:>20.3f}")
# %%
