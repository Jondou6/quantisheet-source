"""Estimating tools (0.13.9 features patch, r36): QuantiSheet's own
checks, templates, customer quotes with options, material order lists,
supplier price list files, crew hours by pay item, bid-day quote
comparison, estimate vs actual, equipment and service records and a
planning-level parametric cost model.

Every module here works on data the user typed or imported. Nothing here
ships prices, rates, cost curves or supplier data, and nothing here makes
a network call. Each module is optional: QuantiSheet runs without this
package's menu, and the package never needs Back Office or ClaimIT.
"""
