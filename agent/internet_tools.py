import logging
import requests
from ddgs import DDGS

logger = logging.getLogger("InternetTools")

def search_internet(query: str, max_results: int = 5) -> str:
    """
    Perform a simple internet search using DuckDuckGo.

    Args:
        query: The search query string.
        max_results: Maximum number of results to return.

    Returns:
        A string containing the search results (titles and snippets).
    """
    logger.info(f"Searching internet for: {query}")
    try:
        with DDGS() as ddgs:
            # Use list() to force execution and catch exceptions
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return "No results found for the query."

            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append(f"{i}. {result['title']}\n   Snippet: {result['body']}\n   URL: {result['href']}\n")

            return "\n".join(formatted_results)
    except Exception as e:
        # DuckDuckGo search can raise exceptions for 'no results' in some versions/cases
        if "No results found" in str(e):
            return "No results found for the query."
        logger.error(f"Internet search error: {str(e)}")
        return f"Error performing internet search: {str(e)}"

def get_weather(location: str) -> str:
    """
    Get current weather for a given location.

    Args:
        location: The city or location name.

    Returns:
        A string describing the current weather.
    """
    logger.info(f"Fetching weather for: {location}")
    try:
        # 1. Geocoding: Location -> Lat/Long
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        geo_params = {"name": location, "count": 1, "language": "en", "format": "json"}
        geo_response = requests.get(geo_url, params=geo_params, timeout=10)
        geo_response.raise_for_status()
        geo_data = geo_response.json()

        if not geo_data.get("results"):
            return f"Could not find coordinates for location: {location}"

        res = geo_data["results"][0]
        lat = res["latitude"]
        lon = res["longitude"]
        name = res["name"]
        country = res.get("country", "Unknown country")

        # 2. Weather: Lat/Long -> Current Weather
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code",
            "timezone": "auto"
        }
        weather_response = requests.get(weather_url, params=weather_params, timeout=10)
        weather_response.raise_for_status()
        weather_data = weather_response.json()

        current = weather_data.get("current", {})
        temp = current.get("temperature_2m")
        code = current.get("weather_code")

        # Weather code mapping (simplified)
        weather_codes = {
            0: "Clear sky",
            1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Depositing rime fog",
            51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
            61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
            71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
            80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
            95: "Thunderstorm"
        }
        condition = weather_codes.get(code, f"Weather code {code}")

        return f"Current weather in {name}, {country}: {temp}°C, {condition}."

    except Exception as e:
        logger.error(f"Weather lookup error: {str(e)}")
        return f"Error fetching weather for {location}: {str(e)}"

# Tool definitions for the LLM
internet_tool_definition = {
    "type": "function",
    "function": {
        "name": "search_internet",
        "description": "Perform a simple internet search to get information about current events, weather, or specific topics.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to use for the internet search."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Defaults to 5."
                }
            },
            "required": ["query"]
        }
    }
}

weather_tool_definition = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a specific location (city, town, etc.).",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "The city or location name to check weather for."
                }
            },
            "required": ["location"]
        }
    }
}

# Mapping for tool execution
INTERNET_TOOL_MAP = {
    "search_internet": search_internet,
    "get_weather": get_weather
}
