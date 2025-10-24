import re
from typing import Optional, Dict, List, Tuple
from wastream.utils.http_client import http_client
from wastream.utils.logger import metadata_logger
from wastream.core.config import settings

# ===========================
# Kitsu Service Class
# ===========================
class KitsuService:

    BASE_URL = settings.KITSU_API_URL
    ALIAS_SERVICE_URL = settings.KITSU_ALIAS_URL

    async def get_metadata(self, kitsu_id: str) -> Optional[Dict]:
        if not kitsu_id or not kitsu_id.strip():
            metadata_logger.error("Empty Kitsu ID")
            return None

        metadata_logger.debug(f"Fetching Kitsu: {kitsu_id}")

        try:
            response = await http_client.get(
                f"{self.BASE_URL}/anime/{kitsu_id}",
                timeout=settings.METADATA_TIMEOUT
            )

            if response.status_code != 200:
                metadata_logger.error(f"Kitsu API {response.status_code}")
                return None

            data = response.json()

            if not data.get("data") or not data["data"].get("attributes"):
                metadata_logger.error("Invalid Kitsu response")
                return None

            attributes = data["data"]["attributes"]

            canonical_title = attributes.get("canonicalTitle", "")
            titles_dict = attributes.get("titles", {})

            year = None
            if attributes.get("startDate"):
                year = attributes["startDate"].split("-")[0]

            search_titles = []
            all_titles = []

            if canonical_title:
                search_titles.append(canonical_title)
                all_titles.append(canonical_title)

            english_title = titles_dict.get("en", "")
            if english_title and english_title.lower() != canonical_title.lower():
                search_titles.append(english_title)

            for title_variant in titles_dict.values():
                if title_variant and title_variant not in all_titles:
                    all_titles.append(title_variant)

            external_aliases = await self._get_aliases(kitsu_id)
            all_titles.extend(external_aliases)

            metadata_logger.debug(f"Kitsu: '{canonical_title}' ({year}) - {len(all_titles)} titles")
            return {
                "title": canonical_title,
                "year": year,
                "subtype": attributes.get("subtype", "TV"),
                "search_titles": search_titles,
                "all_titles": all_titles,
                "aliases": external_aliases,
                "kitsu_id": kitsu_id
            }

        except Exception as e:
            metadata_logger.error(f"Kitsu metadata fetch error: {type(e).__name__}")
            return None

    async def _get_aliases(self, kitsu_id: str) -> List[str]:
        aliases = []

        try:
            response = await http_client.get(
                f"{self.ALIAS_SERVICE_URL}?id={kitsu_id}&provider=Kitsu",
                timeout=settings.METADATA_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()

                if data and len(data) > 0:
                    anime_data = data[0]

                    if anime_data.get("title"):
                        aliases.append(anime_data["title"])

                    if anime_data.get("synonyms"):
                        for synonym in anime_data["synonyms"]:
                            if synonym and synonym not in aliases:
                                aliases.append(synonym)

        except Exception as e:
            metadata_logger.error(f"Kitsu aliases error: {type(e).__name__}")

        return aliases

    async def get_season_chain_and_mapping(self, kitsu_id: str, episode: int) -> Tuple[int, int, Dict, Optional[str], Optional[str], Optional[Dict]]:
        try:
            season_chain = await self._build_season_chain(kitsu_id)

            base_title = season_chain[0]["title"] if season_chain else None
            base_year = season_chain[0]["year"] if season_chain else None

            base_metadata = None
            if season_chain:
                first_season_id = season_chain[0]["id"]
                base_metadata = await self.get_metadata(first_season_id)

            current_position = None
            for i, season_info in enumerate(season_chain):
                if season_info["id"] == kitsu_id:
                    current_position = i
                    break

            if current_position is None:
                metadata_logger.error(f"Kitsu ID {kitsu_id} not in season chain")
                return 1, episode, {}, base_title, base_year, base_metadata

            def _get_base_title(title):
                base = re.sub(r"\s+Part\s+\d+.*$", "", title, flags=re.IGNORECASE)
                base = re.sub(r"\s+part\s+\d+.*$", "", base, flags=re.IGNORECASE)
                return base.strip()

            def _titles_are_same_series(title1, title2):
                base1 = _get_base_title(title1).lower().replace(" ", "").replace(".", "").replace(":", "")
                base2 = _get_base_title(title2).lower().replace(" ", "").replace(".", "").replace(":", "")
                return base1 == base2

            season_groups = []
            used_indices = set()

            for i, season_info in enumerate(season_chain):
                if i in used_indices:
                    continue

                title = season_info["title"]
                current_group = {
                    "season_num": len(season_groups) + 1,
                    "parts": [{"title": title, "episodes": season_info["episodes"], "index": i}]
                }
                used_indices.add(i)

                for j, other_season in enumerate(season_chain):
                    if j in used_indices:
                        continue

                    other_title = other_season["title"]
                    if _titles_are_same_series(title, other_title):
                        current_group["parts"].append({
                            "title": other_title,
                            "episodes": other_season["episodes"],
                            "index": j
                        })
                        used_indices.add(j)

                current_group["parts"].sort(key=lambda x: x["index"])
                season_groups.append(current_group)

            current_group = None
            for group in season_groups:
                for part in group["parts"]:
                    if part["index"] == current_position:
                        current_group = group
                        break
                if current_group:
                    break

            if not current_group:
                metadata_logger.error(f"No season group for position {current_position}")
                actual_season = 1
                episode_offset = 0
            else:
                actual_season = current_group["season_num"]

                episode_offset = 0
                for part in current_group["parts"]:
                    if part["index"] < current_position:
                        episode_offset += part["episodes"]
                        metadata_logger.debug(f"Adding {part['episodes']} episodes from '{part['title']}'")

            actual_episode = episode_offset + episode

            total_episodes_before = sum(s["episodes"] for s in season_chain[:current_position] if s.get("episodes"))
            absolute_episode = total_episodes_before + episode

            is_multi_part = len(season_chain) > 1

            enhanced_metadata = {
                "season_chain": season_chain,
                "current_position": current_position,
                "is_multi_part": is_multi_part,
                "actual_season": actual_season,
                "actual_episode": actual_episode,
                "absolute_episode": absolute_episode,
                "total_episodes_before": total_episodes_before
            }

            return actual_season, actual_episode, enhanced_metadata, base_title, base_year, base_metadata

        except Exception as e:
            metadata_logger.error(f"Kitsu season mapping error: {type(e).__name__}")
            return 1, episode, {}, None, None, None

    async def _build_season_chain(self, kitsu_id: str) -> List[Dict]:
        season_chain = []
        visited = set()

        first_season_id = await self._find_first_season(kitsu_id, visited)

        current_id = first_season_id
        visited.clear()

        while current_id and current_id not in visited:
            visited.add(current_id)

            season_info = await self._get_season_info(current_id)
            if season_info:
                season_chain.append(season_info)

                next_id = await self._get_sequel_id(current_id)
                current_id = next_id
            else:
                break

        return season_chain

    async def _find_first_season(self, kitsu_id: str, visited: set) -> str:
        current_id = kitsu_id

        while current_id and current_id not in visited:
            visited.add(current_id)
            prequel_id = await self._get_prequel_id(current_id)

            if prequel_id and prequel_id not in visited:
                current_id = prequel_id
            else:
                break

        return current_id

    async def _get_season_info(self, kitsu_id: str) -> Optional[Dict]:
        try:
            response = await http_client.get(
                f"{self.BASE_URL}/anime/{kitsu_id}",
                timeout=settings.METADATA_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()
                attributes = data["data"]["attributes"]

                year = None
                if attributes.get("startDate"):
                    year = attributes["startDate"].split("-")[0]

                return {
                    "id": kitsu_id,
                    "title": attributes.get("canonicalTitle", ""),
                    "episodes": attributes.get("episodeCount", 0),
                    "year": year
                }
        except Exception as e:
            metadata_logger.error(f"Kitsu season info error: {type(e).__name__}")

        return None

    async def _get_sequel_id(self, kitsu_id: str) -> Optional[str]:
        return await self._get_related_id(kitsu_id, "sequel")

    async def _get_prequel_id(self, kitsu_id: str) -> Optional[str]:
        return await self._get_related_id(kitsu_id, "prequel")

    async def _get_related_id(self, kitsu_id: str, role: str) -> Optional[str]:
        try:
            response = await http_client.get(
                f"{self.BASE_URL}/anime/{kitsu_id}?include=mediaRelationships.destination",
                timeout=settings.METADATA_TIMEOUT
            )

            if response.status_code == 200:
                data = response.json()

                for item in data.get("included", []):
                    if item["type"] == "mediaRelationships":
                        if item["attributes"]["role"] == role:
                            dest_data = item["relationships"]["destination"]["data"]
                            if dest_data["type"] == "anime":
                                dest_id = dest_data["id"]

                                for included_item in data.get("included", []):
                                    if (included_item["type"] == "anime" and
                                        included_item["id"] == dest_id and
                                        included_item["attributes"].get("subtype") == "TV"):
                                        return dest_id

                                dest_response = await http_client.get(
                                    f"{self.BASE_URL}/anime/{dest_id}",
                                    timeout=settings.METADATA_TIMEOUT
                                )
                                if dest_response.status_code == 200:
                                    dest_anime = dest_response.json()
                                    if dest_anime["data"]["attributes"].get("subtype") == "TV":
                                        return dest_id

        except Exception as e:
            metadata_logger.error(f"Kitsu {role} error: {type(e).__name__}")

        return None

# ===========================
# Singleton Instance
# ===========================
kitsu_service = KitsuService()
