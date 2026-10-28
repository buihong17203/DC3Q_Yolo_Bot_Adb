import sys

try:
    with open(r'C:\Users\Admin\.gemini\antigravity\brain\6781c6db-1368-4866-ba36-33987fedb739\.system_generated\tasks\task-3333.log', 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 2000), 0)
        data = f.read()
        print(data.decode('utf-8', errors='replace').encode('ascii', errors='replace').decode('ascii'))
except Exception as e:
    print(f"Error: {e}")
