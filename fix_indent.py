import re

with open("app.py", "r") as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if "with send_container:" in line:
        start_idx = i
    if "with col_regen:" in line:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    for i in range(start_idx + 1, end_idx):
        if lines[i].startswith("    "):
            lines[i] = lines[i][4:]

with open("app.py", "w") as f:
    f.writelines(lines)

