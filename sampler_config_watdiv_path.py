
# General configuration
ENDPOINT = "http://localhost:8890/sparql"  # URL of the SPARQL endpoint where the KG is hosted (required)
DEFAULT_GRAPH_URI = "http://localhost:8890/watdiv"
SHAPE = "path"  # Shape of subgraphs to generate: "path", "star", "flower", "snowflake"
DATASET = "WatDiv"  # Dataset name (used for output file)
USE_CACHE = True  # Whether to use cached search structures for in memory generation
IN_MEMORY = True  # Whether to use in-memory search and generation instead of sparql endpoint

RDF_FILE_PATH = "data/watdiv.nt"  # Path to RDF file to use

GET_CARDINALITY = True  # Whether to compute cardinality for generated queries in-memory

# Star-specific configuration
# NOTE: MIN_OBJECTS_INSTANTIATED and MAX_OBJECTS_INSTANTIATED are calculated dynamically
# based on query size (min=0, max=ceil(0.5 * size)) in batch sampling
P_PREDICATE = 1.0  # Probability of instantiating predicates (1.0 = always instantiate, 0.0 = never instantiate)

# Path-specific configuration
SAMPLING_METHOD = "dfs"  # Sampling method: "dfs", "bfs" or "random_walk"
P_EDGE = 1.0  # Probability of instantiating a predicate in path queries (1.0 = always instantiate, 0.0 = never instantiate)
P_NODE = 0.05  # Probability of instantiating an intermediate node in path queries
P_START_END = 0.2  # Probability of instantiating start/end node (non-seed) in path queries

# ====== BATCH CONFIGURATION ======
# Specify multiple query sizes and how many queries to generate for each size
# Format: [(size, number_of_queries), (size, number_of_queries), ...]
QUERY_CONFIGURATIONS = [
    (2, 20000)
    (3, 20000),    # Generate 10 queries of size 3 (max objects: ceil(0.5*3) = 2)
    (5, 20000),    # Generate 15 queries of size 5 (max objects: ceil(0.5*5) = 3)
    (8, 20000),    # Generate 20 queries of size 7 (max objects: ceil(0.5*7) = 4)
    (10, 20000),
]