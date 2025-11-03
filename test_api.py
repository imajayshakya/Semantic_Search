import requests
import json
import time

BASE_URL = "http://localhost:8000"

def print_header(title):
    print("\n" + "="*50)
    print(f"====== {title.upper()} ======")
    print("="*50)

def pretty_print(data):
    print(json.dumps(data, indent=2, default=str))

def check_health():
    print_header("Health Check")
    try:
        response = requests.get(f"{BASE_URL}/health")
        response.raise_for_status()
        print("API is healthy!")
        pretty_print(response.json())
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to API. Is it running?")
        exit()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Health check failed: {e}")
        exit()

def insert_tools():
    print_header("1. Inserting Tools")
    tools = [
        {"name": "Numpy", "description": "High-performance, easy-to-use data structures and data analysis library.", "tags": ["python", "data-analysis", "3d-array", "array"]},
        {"name": "ADF", "description": " Azure Data Factory is a managed cloud service that's built for these complex hybrid extract-transform-load (ETL), extract-load-transform (ELT), and data integration projects.", "tags": ["devops", "Pipelines","data", "deployment", "Tool"]},
        {"name": "Flask", "description": "A modern, lightweight web framework for building web apps with Python.", "tags": ["python", "webapp", "api", "web", "development"]},
    ]
    
    inserted_tools = []
    for tool in tools:
        try:
            response = requests.post(f"{BASE_URL}/tools/", json=tool)
            response.raise_for_status()
            print(f"Inserted: {tool['name']}")
            inserted_tools.append(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error inserting {tool['name']}: {e.response.json()}")
            
    print("\n--- Wait 10s for embedding model to download on first run ---")
    time.sleep(10)
    return inserted_tools

def semantic_search():
    print_header("2. Performing Semantic Search")
    queries = [
        "tools for analyzing CSV files",
        "deep learning frameworks",
        "containerization"
    ]
    
    for query in queries:
        print(f"\nSearching for: '{query}'")
        try:
            response = requests.post(f"{BASE_URL}/tools/search", json={"query": query, "limit": 2})
            response.raise_for_status()
            pretty_print(response.json())
        except requests.exceptions.RequestException as e:
            print(f"Error searching: {e.response.json()}")

def crud_test(tool_uuid):
    print_header(f"3. CRUD Test (Create, Read, Update, Delete)")
    
    if not tool_uuid:
        print("No tool UUID provided, skipping CRUD test.")
        return

    # Read
    print(f"\n--- Reading tool {tool_uuid} ---")
    response = requests.get(f"{BASE_URL}/tools/{tool_uuid}")
    pretty_print(response.json())

    # Update
    print(f"\n--- Updating tool {tool_uuid} ---")
    update_data = {"tags": ["python", "data-analysis", "csv", "excel", "UPDATED_TAG"]}
    response = requests.put(f"{BASE_URL}/tools/{tool_uuid}", json=update_data)
    pretty_print(response.json())

    # Delete
    print(f"\n--- Deleting tool {tool_uuid} ---")
    response = requests.delete(f"{BASE_URL}/tools/{tool_uuid}")
    pretty_print(response.json())

    # Verify Delete
    print(f"\n--- Verifying deletion ---")
    response = requests.get(f"{BASE_URL}/tools/{tool_uuid}")
    if response.status_code == 404:
        print("Tool successfully deleted (Got 404 Not Found).")
    else:
        print(f"ERROR: Tool was not deleted. Status code: {response.status_code}")

def show_history():
    print_header("4. Showing Search History")
    try:
        response = requests.get(f"{BASE_URL}/search/history?limit=5")
        response.raise_for_status()
        print("Recent searches:")
        pretty_print(response.json())
    except requests.exceptions.RequestException as e:
        print(f"Error getting history: {e.response.json()}")

def main():
    check_health()
    inserted = insert_tools()
    semantic_search()
    
    # Use the UUID of the first inserted tool (Pandas) for CRUD test
    pandas_uuid = None
    if inserted:
        for tool in inserted:
            if tool['name'] == 'Pandas':
                pandas_uuid = tool['uuid']
                break
    
    crud_test(pandas_uuid)
    show_history()
    print_header("Test Complete")

if __name__ == "__main__":
    main()