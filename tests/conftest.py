import os

# Tests always run against the local docker FalkorDB, never the cloud demo graph.
os.environ["SINEW_LOCAL"] = "1"
