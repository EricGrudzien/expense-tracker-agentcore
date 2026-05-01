"""Tool for building Chart.js chart configurations via the chart-builder Lambda."""

import json
import logging
import os

import boto3

from strands import tool

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "us-east-1")
CHART_BUILDER_LAMBDA = os.environ.get("CHART_BUILDER_LAMBDA", "egru-chart-builder")

logger = logging.getLogger(__name__)


@tool
def chart_builder(
    chart_type: str,
    title: str,
    label_field: str,
    value_field: str,
    data: list,
) -> str:
    """Build a Chart.js chart configuration from data.

    Calls the chart-builder Lambda to produce a Chart.js config that the
    frontend can render. Use this when the user asks for a visual chart
    or graph of their expense data.

    Args:
        chart_type: The type of chart. One of: "bar", "line", "pie", "doughnut".
        title: The chart title to display.
        label_field: The field name in the data to use for chart labels (x-axis or slices).
        value_field: The field name in the data to use for chart values (y-axis or slice sizes).
        data: A list of dictionaries containing the data to chart. Each dict should have keys matching label_field and value_field.
    """
    payload = {
        "chartType": chart_type,
        "title": title,
        "labelField": label_field,
        "valueField": value_field,
        "data": data,
    }

    try:
        lambda_client = boto3.client("lambda", region_name=BEDROCK_REGION)
        resp = lambda_client.invoke(
            FunctionName=CHART_BUILDER_LAMBDA,
            Payload=json.dumps(payload).encode(),
        )
        result = json.loads(resp["Payload"].read())

        if result.get("error"):
            logger.warning(f"Chart build error: {result['error']}")
            return json.dumps({"error": result["error"]})

        chart_config = result.get("chart")
        if chart_config:
            return json.dumps({"chart": chart_config})
        else:
            return json.dumps({"error": "No chart configuration returned"})

    except Exception as e:
        logger.warning(f"Chart build exception: {e}")
        return json.dumps({"error": str(e)})
