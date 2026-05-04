<!-- ABOUTME: Output template for the prompt-squeeze receipt rendered after a compression run. -->
<!-- ABOUTME: Placeholders are filled by scripts/estimate.py --format markdown or by SKILL.md instructions. -->
### Prompt squeeze receipt

Original:    {original_tokens} tokens
Compressed:  {compressed_tokens} tokens   (-{compression_pct})

Estimated savings ({model}):
  Tokens:    {saved_input_tokens} input + ~{saved_output_estimate} output = {saved_total_tokens} tokens
  Dollars:   ${saved_dollars}
  Energy:    {saved_wh} Wh  (~ {saved_g_co2e} g CO2e at US-grid avg)

Methodology: 0.39 J/token x token savings; grid factor 0.4 kg CO2/kWh.
Sources: {energy_source} - {pricing_source}
{tokenizer_inflation_footer}
