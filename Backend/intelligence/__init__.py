"""CareSense AI - FastAPI intelligence / computation service.

This service owns COMPUTATION and MODEL INFERENCE only (spec sections 2, 52).
It never decides which patient a user may access and never reaches into the
primary database. It receives a validated feature payload, a model/task
identifier and a correlation id from Django, and returns computation results.
"""
