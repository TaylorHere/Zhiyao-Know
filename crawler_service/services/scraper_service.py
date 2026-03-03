import json

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig, LLMConfig, LLMExtractionStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from core.config import settings
from schemas.extract import ExtractOptions, UsageInfo


def _normalize_usage(raw_usage: dict | None, model_name: str) -> UsageInfo:
    if not isinstance(raw_usage, dict):
        return UsageInfo(model=model_name)
    return UsageInfo(
        prompt_tokens=int(raw_usage.get("prompt_tokens") or raw_usage.get("prompt") or 0),
        completion_tokens=int(raw_usage.get("completion_tokens") or raw_usage.get("completion") or 0),
        total_tokens=int(raw_usage.get("total_tokens") or raw_usage.get("total") or 0),
        model=raw_usage.get("model") or model_name,
    )


async def extract_with_llm(url: str, json_schema: str, options: ExtractOptions):
    if not settings.api_key:
        raise ValueError("SILICONFLOW_API_KEY or DEEPSEEK_API_KEY is not set")

    try:
        schema = json.loads(json_schema)
    except json.JSONDecodeError as exc:
        raise ValueError("json_schema is not valid JSON") from exc

    input_format = "markdown" if options.html_to_markdown else "html"

    llm_config = LLMConfig(
        provider=settings.llm_provider,
        api_token=settings.api_key,
        base_url=settings.base_url,
    )
    instruction = "请提取网页正文内容，并严格按照提供的 JSON Schema 格式输出。"
    if options.include_images:
        instruction = f"{instruction} 保留正文中的图片信息，优先输出为 Markdown 图片语法或图片链接。"

    extraction_strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        schema=schema,
        extraction_type="schema",
        instruction=instruction,
        input_format=input_format,
        extra_args={"temperature": 0.0},
    )

    run_config = CrawlerRunConfig(
        cache_mode=CacheMode(options.cache_mode),
        extraction_strategy=extraction_strategy,
        wait_until=options.wait_until,
        page_timeout=options.page_timeout,
        wait_for=options.wait_for,
        only_text=options.only_text,
        remove_forms=options.remove_forms,
        exclude_external_links=options.exclude_external_links,
        simulate_user=options.simulate_user,
        magic=options.magic,
    )

    if options.html_to_markdown:
        run_config.markdown_generator = DefaultMarkdownGenerator()
    if options.remove_scripts_styles:
        run_config.excluded_tags = ["script", "style"]

    browser_kwargs = {"headless": True}
    if options.user_agent:
        browser_kwargs["user_agent"] = options.user_agent
    browser_config = BrowserConfig(**browser_kwargs)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not result.success:
        raise RuntimeError(result.error_message or "Crawl failed")

    extracted_content = result.extracted_content or "{}"
    if isinstance(extracted_content, str):
        data = json.loads(extracted_content)
    else:
        data = extracted_content

    raw_usage = None
    if isinstance(result.metadata, dict):
        raw_usage = result.metadata.get("usage") or result.metadata.get("llm_usage")
    if raw_usage is None:
        raw_usage = getattr(extraction_strategy, "usage", None)

    usage = _normalize_usage(raw_usage, settings.llm_model)
    return data, usage


async def crawl_task_target(url: str, options: ExtractOptions | None = None):
    opts = options or ExtractOptions()
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode(opts.cache_mode),
        excluded_tags=["script", "style"],
        wait_until=opts.wait_until,
        page_timeout=opts.page_timeout,
        wait_for=opts.wait_for,
        only_text=opts.only_text,
        remove_forms=opts.remove_forms,
        exclude_external_links=opts.exclude_external_links,
        simulate_user=opts.simulate_user,
        magic=opts.magic,
    )
    browser_kwargs = {"headless": True}
    if opts.user_agent:
        browser_kwargs["user_agent"] = opts.user_agent
    browser_config = BrowserConfig(**browser_kwargs)
    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not result.success:
        raise RuntimeError(result.error_message or "Crawl failed")

    links = result.links or {}
    urls: list[str] = []
    for kind in ("internal", "external"):
        for item in links.get(kind, []):
            href = item.get("href") or item.get("url")
            if href:
                urls.append(href)
    return urls
