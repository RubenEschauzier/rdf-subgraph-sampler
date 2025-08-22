import os
import gzip
import json
import random
import re
import time
from collections import defaultdict, Counter
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import requests
from tqdm import tqdm

P_EDGE = 1          # Prob. of instantiating a predicate
P_NODE = 0.3          # Prob. of instantiating an intermediate node
P_START_END = 0.3     # Prob. of instantiating start/end node (non-seed)
FINAL_QUERY_TIMEOUT = 3
CACHE_SUFFIX = ".path_gen.cache.json"
SAVE_INTERVAL = 300  # Save every 300 queries


_RE_NT_URI_EDGE = re.compile(r"^<([^>]+)>\s+<([^>]+)>\s+<([^>]+)>\s*\.\s*$")

def _parse_nt_line_uri_edge(line: str) -> Optional[Tuple[str, str, str]]:
    """Return (subject, predicate, object) if both ends are URIs, else None."""
    m = _RE_NT_URI_EDGE.match(line)
    if m:
        return m.group(1), m.group(2), m.group(3)
    return None


def _load_graph(rdf_file: str, use_cache: bool = True) -> Dict[str, List[Tuple[str, str]]]:
    """Return adjacency dict: subj -> list[(pred, obj)].
    """
    cache_file = rdf_file + CACHE_SUFFIX
    if use_cache and os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as fh:
                return {k: v for k, v in json.load(fh).items()}
        except Exception:
            print("Warning: failed to read cache – reparsing …")

    adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    open_func = gzip.open if rdf_file.endswith(".gz") else open
    with open_func(rdf_file, "rt", encoding="utf-8", errors="ignore") as fh:
        for ln in fh:
            parsed = _parse_nt_line_uri_edge(ln)
            if parsed:
                s, p, o = parsed
                adj[s].append((p, o))
    print(f"Loaded {len(adj):,} subjects with outgoing URI edges from '{rdf_file}'.")

    if use_cache:
        try:
            with open(cache_file, "w") as fh:
                json.dump(adj, fh)
        except Exception as e:
            print(f"Could not write cache: {e}")

    return adj

def _sample_simple_path(adj: Dict[str, List[Tuple[str, str]]], length: int, max_attempts: int = 100000) -> Optional[Tuple[List[str], List[str]]]:
    """Sample a simple path of specified length using random walk.

    This function performs a random walk through the graph to find a simple path (no repeated nodes)
    of the specified length. At each step, it randomly selects an outgoing edge that leads to an 
    unvisited node. For intermediate nodes, it ensures they have outgoing edges to allow the path
    to continue.

    Args:
        adj: Adjacency dictionary mapping subjects to list of (predicate, object) pairs
        length: Desired length of the path (number of edges)
        max_attempts: Maximum number of random walks to attempt before giving up

    Returns:
        If successful, returns a tuple of:
            - List of nodes (URIs) in the path, including start and end nodes
            - List of predicates (URIs) forming the edges of the path
        If no valid path is found after max_attempts, returns None.
    """
    if length < 1:
        return None
    subjects = list(adj.keys())
    for _ in range(max_attempts):
        start = random.choice(subjects)
        nodes = [start]
        preds: List[str] = []
        current = start
        visited = {start}
        ok = True
        for depth in range(length):
            edges = adj.get(current)
            if not edges:
                ok = False
                break
            random.shuffle(edges)
            found = False
            for p, o in edges:
                if o in visited:
                    continue  # enforce simple path
                # for intermediate steps we need the object to have outgoing edges unless it's the last hop
                if depth < length - 1 and o not in adj:
                    continue
                nodes.append(o)
                preds.append(p)
                visited.add(o)
                current = o
                found = True
                break
            if not found:
                ok = False
                break
        if ok and len(preds) == length:
            return nodes, preds
    return None


def _sample_simple_path_dfs(adj: Dict[str, List[Tuple[str, str]]], length: int, max_attempts: int = 1000, start_node: Optional[str] = None) -> Optional[Tuple[List[str], List[str]]]:
    """Sample a simple path of specified length from the graph using depth-first search.

    Args:
        adj: Adjacency dictionary mapping subjects to list of (predicate, object) pairs
        length: Desired length of the path (number of edges)
        max_attempts: Unused parameter kept for API compatibility
        start_node: Node to start path from. Must be provided.

    Returns:
        If successful, returns a tuple containing:
            - List of nodes (URIs) in the path, including start and end nodes
            - List of predicates (URIs) forming the edges of the path
        If no valid path is found, returns None.
    """
    if length < 1:
        return None
    
    subjects = list(adj.keys())
    
    def dfs_find_path(start_node: str) -> Optional[Tuple[List[str], List[str]]]:
        """Find a simple path of target length using DFS from start_node.
        
        Args:
            start_node: URI of the node to start DFS from

        Returns:
            If successful, returns tuple of (nodes_list, predicates_list)
            If no path found, returns None
        """
        stack = [(start_node, [start_node], [], {start_node})]  # (current_node, path_nodes, path_preds, visited)
        
        while stack:
            current, nodes, preds, visited = stack.pop()
            
            # If we've reached the target length, return the path
            if len(preds) == length:
                return nodes, preds
            
            # Get all outgoing edges from current node
            edges = adj.get(current, [])
            # Randomize edge order to get different paths on different runs
            edges = list(edges)
            random.shuffle(edges)
            
            # Add valid next steps to stack (in reverse order for DFS)
            for pred, obj in reversed(edges):
                if obj in visited:
                    continue  # Skip visited nodes (simple path constraint)
                
                # For intermediate steps, ensure the object has outgoing edges
                if len(preds) < length - 1 and obj not in adj:
                    continue
                
                new_nodes = nodes + [obj]
                new_preds = preds + [pred]
                new_visited = visited | {obj}
                stack.append((obj, new_nodes, new_preds, new_visited))
        
        return None
    
    # If specific start node provided, try only that node
    if start_node is not None:
        return dfs_find_path(start_node)
    else:
        raise ValueError("No start node provided")


def _sample_simple_path_bfs(adj: Dict[str, List[Tuple[str, str]]], length: int, max_attempts: int = 1000, start_node: Optional[str] = None) -> Optional[Tuple[List[str], List[str]]]:
    """BFS-based simple path sampling. Explores paths level by level from random starting points."""
    if length < 1:
        return None
    
    subjects = list(adj.keys())
    
    def bfs_find_path(start_node: str) -> Optional[Tuple[List[str], List[str]]]:
        """Find a simple path of target length using BFS from start_node."""
        from collections import deque
        
        queue = deque([(start_node, [start_node], [], {start_node})])  # (current_node, path_nodes, path_preds, visited)
        
        while queue:
            current, nodes, preds, visited = queue.popleft()
            
            # If we've reached the target length, return the path
            if len(preds) == length:
                return nodes, preds
            
            # Get all outgoing edges from current node
            edges = adj.get(current, [])
            # Randomize edge order to get different paths on different runs
            edges = list(edges)
            random.shuffle(edges)
            
            # Add valid next steps to queue
            for pred, obj in edges:
                if obj in visited:
                    continue  # Skip visited nodes (simple path constraint)
                
                # For intermediate steps, ensure the object has outgoing edges
                if len(preds) < length - 1 and obj not in adj:
                    continue
                
                new_nodes = nodes + [obj]
                new_preds = preds + [pred]
                new_visited = visited | {obj}
                queue.append((obj, new_nodes, new_preds, new_visited))
        
        return None
    
    # If specific start node provided, try only that node
    if start_node is not None:
        return bfs_find_path(start_node)
    
    # Otherwise, try different starting points (original behavior)
    for _ in range(max_attempts):
        start = random.choice(subjects)
        result = bfs_find_path(start)
        if result:
            return result
    
    return None


def _build_query_from_path(nodes: List[str], preds: List[str],
                           p_edge=P_EDGE, p_node=P_NODE, p_start_end=P_START_END) -> Tuple[str, List[str]]:
    """Return (where_clause_str, instantiated_entities) from concrete path."""
    triples = []
    entities = []
    for i, (subj, pred, obj) in enumerate(zip(nodes[:-1], preds, nodes[1:])):
        subj_str = f"?o{i}"
        obj_str = f"?o{i+1}"

        # Only instantiate start node (first triple's subject)
        if i == 0 and random.random() < p_start_end:
            subj_str = f"<{subj}>"
            entities.append(subj)
        
        # Only instantiate end node (last triple's object) 
        if i == len(preds)-1 and random.random() < p_start_end:
            obj_str = f"<{obj}>"
            entities.append(obj)

        # IMPORTANT: Never instantiate intermediate nodes as this breaks path connectivity
        # The variables ?o1, ?o2, ?o3, etc. must remain as variables to link the triples

        # Predicate instantiation
        pred_str = f"<{pred}>" if random.random() < p_edge else f"?p{i+1}"
        if pred_str.startswith("<"):
            entities.append(pred)

        triples.append(f"{subj_str} {pred_str} {obj_str}")

    where_clause = " . ".join(triples)
    return where_clause, entities


def _save_queries(generated: List[dict], dataset_name: str, n_triples: int, 
                  sampling_method: str, timestamp: datetime, is_final: bool = False) -> str:
    """Save queries to file with consistent naming. Returns filename."""
    if is_final:
        suffix = "_final"
    else:
        suffix = ""  # No suffix for periodic saves - always overwrite the same file
    
    fn = f"{dataset_name}_path_{timestamp.strftime('%Y-%m-%d_%H-%M-%S')}_{n_triples}_{sampling_method}{suffix}.json"
    
    with open(fn, "w") as fh:
        json.dump(generated, fh, indent=2)
    
    status = "Final" if is_final else "Partial"
    print(f"{status} save: {len(generated)} queries → {fn}")
    return fn


def _get_cardinality(endpoint_url: str, where_clause: str, timeout: int = FINAL_QUERY_TIMEOUT,
                     default_graph_uri = None) -> int:
    query = f"SELECT (COUNT(*) as ?c) WHERE {{ {where_clause} }}"
    try:
        params = {
            'query': query,
            'format': 'json',
        }
        if default_graph_uri:
            params['default-graph-uri'] = default_graph_uri

        r = requests.get(endpoint_url, params=params, timeout=timeout)
        if r.status_code == 200:
            bindings = r.json().get('results', {}).get('bindings', [])
            if bindings and 'c' in bindings[0]:
                return int(bindings[0]['c']['value'])
    except Exception as e:
        print(f"Cardinality request failed: {e}")
    return -1


def get_queries(rdf_file: str,
                dataset_name: str,
                n_triples: int = 1,
                n_queries: int = 10_000,
                endpoint_url: Optional[str] = None,
                default_graph_uri = None,
                outfile: bool = True,
                get_cardinality: bool = False,
                use_cache: bool = True,
                sampling_method: str = "random_walk",
                enable_timing: bool = True,
                p_edge: float = P_EDGE,
                p_node: float = P_NODE,
                p_start_end: float = P_START_END) -> List[dict]:
    """Generate *n_queries* random simple-path queries of exact length *n_triples*.
    
    Args:
        sampling_method: One of "random_walk", "dfs", "bfs", or "random_walk_optimized"
        enable_timing: If True, prints timing information for DFS/BFS sampling calls
        p_edge: Probability of instantiating a predicate (default: P_EDGE)
        p_node: Probability of instantiating an intermediate node (default: P_NODE)
        p_start_end: Probability of instantiating start/end node (default: P_START_END)
    """
    if not rdf_file or not os.path.exists(rdf_file):
        raise FileNotFoundError(f"RDF file '{rdf_file}' not found")

    print(f"Parsing graph …")
    adj = _load_graph(rdf_file, use_cache=use_cache)

    # Select the sampling function based on method
    if sampling_method == "dfs":
        sample_func = _sample_simple_path_dfs
        print(f"[EnhancedPathGen] Using DFS-based sampling")
    elif sampling_method == "bfs":
        sample_func = _sample_simple_path_bfs
        print(f"[EnhancedPathGen] Using BFS-based sampling")
    else:  # default to original random walk
        sample_func = _sample_simple_path
        print(f"[EnhancedPathGen] Using original random walk sampling")

    print(f"[EnhancedPathGen] Sampling {n_queries} unique path queries of length {n_triples} …")
    now = datetime.now()
    generated: List[dict] = []
    seen_hashes = set()

    with tqdm(total=n_queries, desc="Generating") as pbar:
        last_save_count = 0  # Track when we last saved (shared across both methods)
        
        if sampling_method in ["dfs", "bfs"]:
            # Systematic approach for DFS/BFS - go through each subject once
            subjects = list(adj.keys())
            random.shuffle(subjects)
            subject_idx = 0
            attempts = 0
            total_sampling_time = 0.0
            successful_subjects = 0
            
            # Create a separate progress bar for systematic subject processing
            with tqdm(total=len(subjects), desc=f"{sampling_method.upper()} Subjects", 
                     position=1, leave=False) as subject_pbar:
                
                while len(generated) < n_queries and subject_idx < len(subjects):
                    # Try current subject
                    start = subjects[subject_idx]
                    
                    # Time the sampling function call if timing is enabled
                    if enable_timing:
                        start_time = time.time()
                        sp = sample_func(adj, n_triples, start_node=start)
                        end_time = time.time()
                        sampling_time = end_time - start_time
                        total_sampling_time += sampling_time
                    else:
                        sp = sample_func(adj, n_triples, start_node=start)
                    
                    if sp:
                        successful_subjects += 1
                        nodes, preds = sp
                        where_clause, entities = _build_query_from_path(nodes, preds, p_edge=p_edge, p_node=p_node, p_start_end=p_start_end)
                        query_str = f"SELECT * WHERE {{ {where_clause} }}"
                        hash_key = hash(where_clause) # simpler hashing for paths since the path is ordered and variable naming always the same
                        
                        if hash_key not in seen_hashes:
                            seen_hashes.add(hash_key)
                            
                            y = -1
                            if endpoint_url and get_cardinality:
                                y = _get_cardinality(endpoint_url, where_clause, default_graph_uri=default_graph_uri)

                            triple_list = [t.split() for t in where_clause.split(" . ")]
                            generated.append({
                                "x": entities,
                                "y": y,
                                "query": query_str,
                                "triples": triple_list
                            })
                            pbar.update(1)
                            
                            # Periodic saving every SAVE_INTERVAL queries
                            if outfile and len(generated) - last_save_count >= SAVE_INTERVAL:
                                _save_queries(generated, dataset_name, n_triples, sampling_method, now, is_final=False)
                                last_save_count = len(generated)

                    
                    # Update subject progress bar with current stats
                    subject_idx += 1
                    success_rate = (successful_subjects / subject_idx * 100) if subject_idx > 0 else 0
                    subject_pbar.set_description(f"{sampling_method.upper()} | Queries: {len(generated)}/{n_queries} | Success: {success_rate:.1f}%")
                    subject_pbar.update(1)
                    
                    # Early exit if we have enough queries
                    if len(generated) >= n_queries:
                        break
                
                # If we've gone through all subjects but need more queries, 
                # shuffle and start over (but this shouldn't usually happen with DFS/BFS)
                if subject_idx >= len(subjects) and len(generated) < n_queries:
                    random.shuffle(subjects)
                    subject_idx = 0
                    attempts += 1

            
            # Print timing summary if timing was enabled
            if enable_timing:
                avg_time = total_sampling_time / subject_idx if subject_idx > 0 else 0
                print(f"\n[TIMING SUMMARY] {sampling_method.upper()}")
                print(f"  Total subjects tried: {subject_idx}")
                print(f"  Successful subjects: {successful_subjects} ({successful_subjects/subject_idx*100:.1f}%)")
                print(f"  Total sampling time: {total_sampling_time:.4f}s")
                print(f"  Average time per subject: {avg_time:.6f}s")
                print(f"  Successful queries generated: {len(generated)}")
        else:
            # Random approach for random walk methods
            attempts = 0
            while len(generated) < n_queries and attempts < 100:
                attempts += 1
                sp = sample_func(adj, n_triples)
                if not sp:
                    print(f"No simple path of length {n_triples} found – skipping attempt {attempts}.")
                    continue  # try another attempt
                nodes, preds = sp
                where_clause, entities = _build_query_from_path(nodes, preds, p_edge=p_edge, p_node=p_node, p_start_end=p_start_end)
                query_str = f"SELECT * WHERE {{ {where_clause} }}"
                hash_key = hash(where_clause)
                if hash_key in seen_hashes:
                    continue
                seen_hashes.add(hash_key)

                y = -1
                if endpoint_url and get_cardinality:
                    y = _get_cardinality(endpoint_url, where_clause, default_graph_uri=default_graph_uri)

                triple_list = [t.split() for t in where_clause.split(" . ")]
                generated.append({
                    "x": entities,
                    "y": y,
                    "query": query_str,
                    "triples": triple_list
                })
                pbar.update(1)
                
                # Periodic saving every SAVE_INTERVAL queries
                if outfile and len(generated) - last_save_count >= SAVE_INTERVAL:
                    _save_queries(generated, dataset_name, n_triples, sampling_method, now, is_final=False)
                    last_save_count = len(generated)

    # Final save only if we have new queries since the last partial save
    if outfile:
        if len(generated) > last_save_count:
            fn = _save_queries(generated, dataset_name, n_triples, sampling_method, now, is_final=True)
        else:
            print(f"Final save skipped: all {len(generated)} queries already saved in partial saves.")

    return generated

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Enhanced offline path query generator")
    parser.add_argument("rdf_file", help="Path to .nt or .nt.gz file")
    parser.add_argument("dataset_name", help="Dataset tag for output file names")
    parser.add_argument("--length", type=int, default=3, help="Number of triple patterns in each query")
    parser.add_argument("--num", type=int, default=1000, help="Number of queries to generate")
    parser.add_argument("--endpoint", help="SPARQL endpoint for optional cardinality calculation")
    parser.add_argument("--card", action="store_true", help="Ask endpoint for COUNT(*) of each query")
    parser.add_argument("--no-cache", action="store_true", help="Disable on-disk cache")
    parser.add_argument("--method", type=str, default="random_walk", 
                       choices=["random_walk", "dfs", "bfs", "random_walk_optimized"],
                       help="Sampling method: random_walk (default), dfs, bfs, or random_walk_optimized")
    parser.add_argument("--timing", action="store_true", 
                       help="Enable timing output for DFS/BFS sampling calls")
    args = parser.parse_args()

    get_queries(
        rdf_file=args.rdf_file,
        dataset_name=args.dataset_name,
        n_triples=args.length,
        n_queries=args.num,
        endpoint_url=args.endpoint,
        outfile=True,
        get_cardinality=args.card,
        use_cache=not args.no_cache,
        sampling_method=args.method,
        enable_timing=args.timing
    )
