# vsg_core/job_layouts/signature.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
import json
from collections import Counter
from typing import Dict, List, Any

class EnhancedSignatureGenerator:
    """
    Generates robust signatures for track matching and layout compatibility.
    Handles duplicate tracks (e.g., PGS) by including their position.
    """

    def generate_track_signature(self, track_info: Dict[str, List[dict]], strict: bool = False) -> Dict[str, Any]:
        """
        Generates a basic signature for a set of tracks.

        Args:
            track_info: Dictionary mapping source names to their track lists.
            strict: If True, includes codec and language for a stricter match.

        Returns:
            A dictionary representing the signature.
        """
        if not strict:
            # Non-strict signature: counts tracks by source and type.
            signature = Counter(
                f"{track['source']}_{track['type']}"
                for source_tracks in track_info.values()
                for track in source_tracks
            )
        else:
            # Strict signature: includes codec, language, and position to differentiate identical tracks.
            signature_items = []
            type_counters = {}
            for source_key, tracks in track_info.items():
                for track in tracks:
                    track_type = track.get('type', 'unknown')
                    position = type_counters.get(track_type, 0)
                    type_counters[track_type] = position + 1

                    sig_item = (
                        f"{track['source']}_{track['type']}_"
                        f"{track.get('codec_id', '').lower()}_{track.get('lang', 'und').lower()}_{position}"
                    )
                    signature_items.append(sig_item)
            signature = Counter(signature_items)

        return {
            'signature': dict(signature),
            'strict': strict,
            'total_tracks': sum(signature.values())
        }

    def generate_structure_signature(self, track_info: Dict[str, List[dict]]) -> Dict[str, Any]:
        """
        Generates a detailed, order-sensitive signature of the file structure.
        This is used for exact compatibility checking.

        CRITICAL FIX: Now includes track IDs to prevent layouts from being applied
        to files where tracks are in different orders.
        """
        structure = {}
        for source_key, tracks in sorted(track_info.items()):
            source_structure = {'video': [], 'audio': [], 'subtitles': []}
            for track in tracks:
                track_type = track.get('type')
                if track_type in source_structure:
                    source_structure[track_type].append({
                        'id': track.get('id'),  # ADDED: Track ID for exact matching
                        'codec_id': track.get('codec_id', ''),
                        'lang': track.get('lang', 'und'),
                    })
            structure[source_key] = source_structure

        structure_json = json.dumps(structure, sort_keys=True)
        structure_hash = hashlib.sha256(structure_json.encode()).hexdigest()

        return {'structure': structure, 'hash': structure_hash}

    def structures_are_compatible(self, struct1: Dict[str, Any], struct2: Dict[str, Any]) -> bool:
        """Compares two structure signatures for exact compatibility."""
        return struct1.get('hash') and struct1.get('hash') == struct2.get('hash')
