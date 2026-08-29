from dataclasses import dataclass


@dataclass(frozen=True)
class UsageTotals:
    input_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def input_related_tokens(self):
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    @property
    def total_processed_tokens(self):
        return self.input_related_tokens + self.output_tokens


def _get(row, camel, snake):
    return row.get(camel, row.get(snake, 0)) or 0


def parse_usage(result):
    raw = result.get("modelUsage", result.get("model_usage", {}))
    rows = raw.values() if isinstance(raw, dict) else raw
    values = list(rows)
    return UsageTotals(
        sum(_get(row, "inputTokens", "input_tokens") for row in values),
        sum(_get(row, "cacheCreationInputTokens", "cache_creation_input_tokens") for row in values),
        sum(_get(row, "cacheReadInputTokens", "cache_read_input_tokens") for row in values),
        sum(_get(row, "outputTokens", "output_tokens") for row in values),
        sum(float(_get(row, "costUSD", "cost_usd")) for row in values),
    )
