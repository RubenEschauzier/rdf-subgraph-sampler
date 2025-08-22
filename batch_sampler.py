import sys
import math
from samplers import star_query_generator as star_sampler
# Import the file-based version
from samplers import star_query_generator_in_memory as file_sampler_in_memory
from samplers import path_query_generator as path_sampler
from samplers import path_query_generator_in_memory as path_sampler_in_memory
#from samplers import complex_query_generator as complex_sampler

# Import configuration
from sampler_config_watdiv_star import *


def run_sampler_for_config(size, queries, config):
    """Run the sampler for a specific size and query count configuration"""
    print(f"\n=== Generating {queries} queries of size {size} ===")
    
    # Update dataset name to include size info
    dataset_name = f"{config['DATASET']}_SIZE_{size}"
    
    # Calculate min and max objects instantiated based on query size
    min_objects_instantiated = 0
    max_objects_instantiated = math.ceil(0.5 * size)
    
    print(f"Objects instantiated: min={min_objects_instantiated}, max={max_objects_instantiated}")
    
    if config['SHAPE'] == 'star':
        if config['IN_MEMORY']:
            print("Using In Memory star generation...")
            file_sampler_in_memory.get_queries(
                None, dataset_name, size, queries, config['ENDPOINT'],
                default_graph_uri=config['DEFAULT_GRAPH_URI'],
                use_cache=config['USE_CACHE'], 
                min_objects_instantiated=min_objects_instantiated,
                max_objects_instantiated=max_objects_instantiated,
                rdf_file=config['RDF_FILE_PATH'], 
                p_predicate=config['P_PREDICATE'], 
                get_cardinality=config['GET_CARDINALITY']
            )
        else:
            print("Using endpoint-based star generation...")
            star_sampler.get_queries(None, dataset_name, size, queries, config['ENDPOINT'], use_cache=config['USE_CACHE'])
    elif config['SHAPE'] == 'path':
        if config['IN_MEMORY']:
            print("Using In Memory path generation...")
            path_sampler_in_memory.get_queries(
                rdf_file=config['RDF_FILE_PATH'],
                dataset_name=dataset_name,
                n_triples=size,
                n_queries=queries,
                endpoint_url=config['ENDPOINT'] if config['GET_CARDINALITY'] else None,
                default_graph_uri=config['DEFAULT_GRAPH_URI'],
                outfile=True,
                get_cardinality=config['GET_CARDINALITY'],
                use_cache=config['USE_CACHE'],
                sampling_method=config['SAMPLING_METHOD'],
                enable_timing=False,
                p_edge=config['P_EDGE'],
                p_node=config['P_NODE'],
                p_start_end=config['P_START_END']
            )
        else:
            print("Using endpoint-based path generation...")
            path_sampler.get_queries(None, dataset_name, size, queries, config['ENDPOINT'])
    #elif config['SHAPE'] == 'flower' or config['SHAPE'] == 'snowflake':
    #    complex_sampler.get_queries(None, dataset_name, config['SHAPE'], size, queries, config['ENDPOINT'])


if __name__ == "__main__":  
    # Validation
    if not ENDPOINT and not IN_MEMORY:
        print("error: no ENDPOINT specified. Please set the ENDPOINT variable to specify the address of a server.")
        sys.exit(1)

    if not QUERY_CONFIGURATIONS:
        print("error: no QUERY_CONFIGURATIONS specified. Please add at least one (size, queries) tuple.")
        sys.exit(1)

    # Create config dictionary to pass to function
    config = {
        'ENDPOINT': ENDPOINT,
        'SHAPE': SHAPE,
        'DATASET': DATASET,
        'USE_CACHE': USE_CACHE,
        'IN_MEMORY': IN_MEMORY,
        'RDF_FILE_PATH': RDF_FILE_PATH,
        'GET_CARDINALITY': GET_CARDINALITY,
        'P_PREDICATE': P_PREDICATE,
        'SAMPLING_METHOD': SAMPLING_METHOD,
        'P_EDGE': P_EDGE,
        'P_NODE': P_NODE,
        'P_START_END': P_START_END,
        'DEFAULT_GRAPH_URI': DEFAULT_GRAPH_URI
    }

    print(f"Starting batch generation for {len(QUERY_CONFIGURATIONS)} configurations...")
    print(f"Shape: {SHAPE}, In-memory: {IN_MEMORY}")
    print("Objects instantiated will be calculated dynamically: min=0, max=ceil(0.5 * query_size)")
    
    # Run sampler for each configuration
    for size, queries in QUERY_CONFIGURATIONS:
        try:
            run_sampler_for_config(size, queries, config)
            print(f"✓ Completed: {queries} queries of size {size}")
        except Exception as e:
            print(f"✗ Failed for size {size}, queries {queries}: {str(e)}")
            # Continue with next configuration even if one fails
            continue
    
    print("\n=== Batch generation completed ===") 