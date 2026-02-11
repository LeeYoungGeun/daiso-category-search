# NLU Failure Case Classification

This document defines types of failures to look for when evaluating the NLU system.

## 1. Intent Mismatch
- **Definition**: The model identified the wrong intent (e.g., `SEARCH` instead of `CHIT_CHAT`).
- **Example**: 
  - Input: "Hello"
  - Expected: `CHIT_CHAT`
  - Actual: `SEARCH` (product_name="Hello")

## 2. Slot Extraction Failure
- **Definition**: Critical information was present in the text but missed by the model.
- **Example**:
  - Input: "Blue chair under 10000 won"
  - Expected: `color="Blue"`, `price_max=10000`
  - Actual: `product_name="chair"`, `price_max=null`

## 3. Hallucination
- **Definition**: The model invented information not present in the input.
- **Example**:
  - Input: "Storage box"
  - Actual: `category="Kitchen"` (User didn't specify kitchen)

## 4. Poor Tail Question
- **Definition**: The clarification question is irrelevant, repetitive, or awkward.
- **Example**:
  - Input: "I need a cup"
  - Question: "Do you need a cup?" (Redundant)

## 5. JSON Parsing Error
- **Definition**: The model failed to produce valid JSON.
