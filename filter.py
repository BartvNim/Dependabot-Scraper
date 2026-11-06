import json
import os

def filter_prs(data):
    filtered_list = []
    
    for pr in data:
        repo = pr.get('repository', {})
        
        # Extracting nested values
        stars = repo.get('stargazerCount', 0)
        is_fork = repo.get('isFork', False)
        
        # Digging into defaultBranchRef -> target -> history -> totalCount
        default_branch = repo.get('defaultBranchRef') or {}
        target = default_branch.get('target') or {}
        history = target.get('history') or {}
        total_commits = history.get('totalCount', 0)
        
        # Apply your logic
        if stars > 10 and not is_fork and total_commits > 20:
            filtered_list.append(pr)
            
    return filtered_list

if __name__ == "__main__":
    for file in os.listdir("./scraped_days"):
        input_path = os.path.join("./scraped_days", file)
        output_path = os.path.join("./filtered_days", file)
        print(file)
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # The data must be a list for this logic to work
            if isinstance(data, list):
                refined_data = filter_prs(data)
                
                # Only save if we actually found matches
                if refined_data:
                    with open(output_path, 'w', encoding='utf-8') as f_out:
                        json.dump(refined_data, f_out, indent=4)
                
                print(f'{file} saved with {len(refined_data)}')
            
        except Exception as e:
            print(f"Error for {file}: {e}")
                