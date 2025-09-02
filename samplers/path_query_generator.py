import json
from tqdm import tqdm
import requests
import random
from datetime import datetime
import itertools  # Added for generating pair-wise inequality combinations

# SEED_PATH_LEN: Tune according the capacity of the endpoint
SEED_PATH_LEN = 6
# SEED_BATCHES: Should be high (over 300) for short path queries, and small (10) for long path queries
SEED_BATCHES = 1
# ENDPOINT_LIMIT: Should be high for short path queries, adjust according to the capacity of the endpoint
ENDPOINT_LIMIT = 10000 # 5000
# QUERIES_PER_SEED: Set up to 1 for short path queries, 3 for long path queries (with length >= 5)
QUERIES_PER_SEED = 3
# P_EDGE: Can stay like this
P_EDGE = 0.9
# P_NODE: Can stay like this
P_NODE = 0.3
# FINAL_QUERY_TIMEOUT: Can be set up higher for long path queries
FINAL_QUERY_TIMEOUT = 10
# P_START_END: Probability of instantiating the start or end of the path
P_START_END = 0.3
# DEFAULT_GRAPH_URI Default graph uri to query
DEFAULT_GRAPH_URI = "http://localhost:8890/yago"

def generate_template(n_triples, start=1):
    where = ""
    for i in range(start, n_triples + 1):
        where += " ?o" + str(i - 1) + " ?p" + str(i) + " ?o" + str(i) + " . "
    return where


def get_seed_paths(path, endpoint_url, path_length):
    project = ["?p"+str(i) for i in range(1, path_length+1)]
    query = "SELECT DISTINCT " + ' '.join(project) + " WHERE { " + path + " } " + \
            "" + "LIMIT " + str(ENDPOINT_LIMIT)
    
    print(f"Querying endpoint: {endpoint_url}")
    print(f"Query: {query}")
    
    r = requests.get(endpoint_url,
                     params={'query': query, 'format': 'json','default-graph-uri': DEFAULT_GRAPH_URI})
    
    print(f"Status code: {r.status_code}")
    print(f"Response headers: {r.headers}")
    print(f"Response text (first 200 chars): {r.text[:200]}")
    
    if r.status_code != 200:
        raise Exception(f"HTTP {r.status_code}: {r.text}")
    
    try:
        res = r.json()
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON. Full response: {r.text}")
        raise e
    
    res = res["results"]["bindings"]
    return res


def instantiate_path(bindings, query, seed=False, factor=1, path_len=1):
    entities = []
    for (k, v) in bindings.items():
        # Instantiate predicate in path with very high probability
        if k.startswith("p") and random.random() < P_EDGE:
            query = query.replace("?" + k, "<" + bindings[k]['value'] + ">")
            entities.append(bindings[k]['value'])
        # Instantiate last node in the non-seed paths with some probability
        elif not seed and k == 'o'+str(path_len) and random.random() < P_START_END:
            if bindings[k]['type'] == 'uri':
                query = query.replace("?" + k, "<" + bindings[k]['value'] + ">")
                entities.append(bindings[k]['value'])
            else:
                query = query.replace("?" + k, '"' + bindings[k]['value'] + '"')
                entities.append(bindings[k]['value'])
        # Instantiate starting node in the non-seed paths with some probability
        elif not seed and k == 'o0' and random.random() < P_START_END:
            query = query.replace("?" + k, "<" + bindings[k]['value'] + ">")
            entities.append(bindings[k]['value'])
        # Instantiate intermediate node in path with random probability
        elif bindings[k]['type'] == 'uri' and random.random() < (P_NODE * factor):
            query = query.replace("?" + k, "<" + bindings[k]['value'] + ">")
            entities.append(bindings[k]['value'])
    return query, entities


def get_queries(graphfile, dataset_name, n_triples=1, n_queries=30000, endpoint_url=None, outfile=True, get_cardinality=True):
    now = datetime.now()

    # Determine length of seed path
    spl = min(SEED_PATH_LEN, n_triples)

    # ------------------ Pre-check for path existence ------------------
    if endpoint_url:
        print(f"Checking if any simple path of length {n_triples} exists …")
        if not _path_exists(endpoint_url, n_triples, distinct_nodes=True):
            print(f"No simple path of length {n_triples} found – aborting generation.")
            return []
        else:
            print(f"Simple path of length {n_triples} found – continuing generation.")
    # -----------------------------------------------------------------

    # Get candidate paths of length SEED_PATH_LEN
    print("Getting seed paths of length", spl)
    path = generate_template(spl, 1)
    res = []
    for i in tqdm(range(0, SEED_BATCHES)):
        res += get_seed_paths(path, endpoint_url, spl)

    print("Generating path queries ...")
    res = [x for n, x in enumerate(res) if res.index(x) == n]
    testdata = []
    #for i in range(0, n_queries):
    for i in tqdm(range(0, n_queries)):
        try:
            # Select a seed path to instantiate the first part of the path, and extend query
            j = random.randint(0, len(res) - 1)
            query_j, entities = instantiate_path(res[j], path, seed=True, factor=0.01)
            query_expansion = generate_template(n_triples, spl + 1)

            rj = requests.get(endpoint_url,
                              params={'query': "SELECT * WHERE { " + query_j + query_expansion + " } LIMIT 1000",
                                      'format': 'json','default-graph-uri': DEFAULT_GRAPH_URI},
                              timeout=8)

            if rj.status_code == 200:
                qres = rj.json()
                qres = qres["results"]["bindings"]

                if not qres:
                    continue

                # Expand the query with new bindings to get the final query
                for k in range(0, QUERIES_PER_SEED):
                    n = random.randint(0, len(qres) - 1)
                    final_query, entities2 = instantiate_path(qres[n], query_j + query_expansion, factor=0.1, path_len=n_triples)

                    if not get_cardinality:
                        testdata.append({"query": "SELECT * WHERE { " + final_query + " }",
                                         "triples": [elem.strip().split() for elem in final_query.split(" .")[:-1]]})
                        continue

                    # Get cardinality of query
                    rn = requests.get(endpoint_url,
                                      params={'query': "SELECT COUNT(*) as ?res WHERE { " + final_query + " }",
                                              'format': 'json', 'default-graph-uri': DEFAULT_GRAPH_URI},
                                      timeout=FINAL_QUERY_TIMEOUT)
                    if rn.status_code == 200:
                        qres2 = rn.json()
                        qres2 = qres2["results"]["bindings"]
                        datapoint = {"x": entities + entities2,
                                     "y": int(qres2[0]["res"]["value"]),
                                     "query": "SELECT * WHERE { " + final_query + " }",
                                     "triples": [elem.strip().split() for elem in final_query.split(" . ")[:-1]]}
                        testdata.append(datapoint)
                        #print(qres2[0]["res"]["value"], "SELECT * WHERE { " + final_query + " }")

        except requests.exceptions.ReadTimeout:
            pass

        if outfile and i % 100 == 0:
            with open(dataset_name + "_path_" + now.strftime('%Y-%m-%d_%H-%M-%S_') + str(n_triples) + ".json", "w") as fp:
                json.dump(testdata, fp)

    # Write output
    if outfile:
        with open(dataset_name + "_path_" + now.strftime('%Y-%m-%d_%H-%M-%S_') + str(n_triples) + ".json", "w") as fp:
            json.dump(testdata, fp)

    print("Done:", len(testdata))
    return testdata


# NEW: -------------------------------------------------------------
# Helper to build and execute an ASK query that checks if a simple
# path (all nodes distinct) of a given length exists in the graph.
# -----------------------------------------------------------------

def _build_path_ask_query(length: int, distinct_nodes: bool = True) -> str:
    """Return an ASK query that looks for at least one path of *length*.

    Parameters
    ----------
    length : int
        Number of edges in the path (>=1).
    distinct_nodes : bool, default True
        If True the query enforces that all nodes in the walk are pair-wise
        different, i.e. searches for a *simple* path.
    """
    vars_ = [f"?v{i}" for i in range(length + 1)]
    triple_lines = "\n  ".join(f"{vars_[i]} ?p{i+1} {vars_[i+1]} ." for i in range(length))

    filter_part = ""
    if distinct_nodes:
        # Create all pair-wise inequality constraints
        neq_parts = [f"{a} != {b}" for a, b in itertools.combinations(vars_, 2)]
        filter_part = f"\n  FILTER ( {' && '.join(neq_parts)} )" if neq_parts else ""

    return f"ASK WHERE {{\n  {triple_lines}{filter_part}\n}}"

def _path_exists(endpoint_url: str, length: int, distinct_nodes: bool = True, timeout: int = 100) -> bool:
    """Return True iff the KG accessible at *endpoint_url* contains a path of
    exact *length* edges. If *distinct_nodes* is True, the nodes must all be
    different. Handles network / parsing errors gracefully by returning
    False.
    """
    ask_query = _build_path_ask_query(length, distinct_nodes)
    print(f"Query: {ask_query}")
    try:
        r = requests.get(
            endpoint_url,
            params={'query': ask_query, 'format': 'json', 'default-graph-uri': DEFAULT_GRAPH_URI},
            timeout=timeout
        )
        if r.status_code != 200:
            print(f"Warning: ASK query failed with HTTP {r.status_code}: {r.text[:200]}")
            return False
        res = r.json()
        return bool(res.get('boolean'))
    except Exception as e:
        print(f"Error executing ASK query: {e}")
        return False


if __name__ == "__main__":
    get_queries(None, "yago", n_triples=8, n_queries=20000,
                 endpoint_url="http://localhost:8890/sparql", outfile=True)

