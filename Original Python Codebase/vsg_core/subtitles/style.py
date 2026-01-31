# -*- coding: utf-8 -*-
from pathlib import Path
from ..io.runner import CommandRunner

def multiply_font_size(subtitle_path: str, multiplier: float, runner: CommandRunner) -> bool:
    sub_path = Path(subtitle_path)
    if sub_path.suffix.lower() not in ['.ass', '.ssa'] or multiplier == 1.0:
        return False
    runner._log_message(f'[Font Size] Applying {multiplier:.2f}x size multiplier to {sub_path.name}.')
    try:
        lines = sub_path.read_text(encoding='utf-8-sig').splitlines()
        new_lines, modified = [], 0
        for line in lines:
            if line.strip().lower().startswith('style:'):
                parts = line.split(',', 3)
                if len(parts) >= 4:
                    try:
                        style_prefix = f"{parts[0]},{parts[1]}"
                        original_size = float(parts[2])
                        style_suffix = parts[3]
                        new_size = int(round(original_size * multiplier))
                        new_lines.append(f"{style_prefix},{new_size},{style_suffix}")
                        modified += 1; continue
                    except Exception:
                        pass
            new_lines.append(line)
        if modified > 0:
            sub_path.write_text('\n'.join(new_lines), encoding='utf-8')
            runner._log_message(f'[Font Size] Modified {modified} style definition(s).')
            return True
        runner._log_message(f'[Font Size] WARN: No style definitions found to modify in {sub_path.name}.')
        return False
    except Exception as e:
        runner._log_message(f'[Font Size] ERROR: Could not process {sub_path.name}: {e}')
        return False
