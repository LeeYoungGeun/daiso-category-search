# M1 Hybrid Search Benchmark Report

**Date**: 2026-02-10 16:37:10
**Test Cases**: 88

## Results Comparison

| Metric | hybrid | bm25_only | dense_only |
|--------|--------|--------|--------|
| hit@1 | 84.1% | 79.5% | 89.8% |
| hit@3 | 97.7% | 92.0% | 95.5% |
| hit@5 | 98.9% | 97.7% | 100.0% |
| hit@10 | 100.0% | 100.0% | 100.0% |
| mrr | 90.8% | 86.6% | 93.3% |
| ndcg@5 | 91.5% | 87.8% | 93.1% |
| ndcg@10 | 92.8% | 89.6% | 93.7% |
| avg_latency_ms | 375ms | 24ms | 352ms |

## Failures

### hybrid (1 failures)
- **tc_4022**: `마우스 패드 마우스패드 컴퓨터 데스크 게이밍 논슬립` → expected: ['mouse_pad_basic']

### bm25_only (2 failures)
- **tc_4022**: `마우스 패드 마우스패드 컴퓨터 데스크 게이밍 논슬립` → expected: ['mouse_pad_basic']
- **tc_4041**: `풀 접착제 딱풀 고체풀 문구 사무용품 학용품` → expected: ['glue_stick_basic']