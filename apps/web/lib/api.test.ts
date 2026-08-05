import {describe, expect, it} from "vitest";
import {ApiError, humanError} from "./api";

describe("API errors", () => {
  it("renders structured validation errors in Chinese", () => {
    const message = humanError(new ApiError(422, {message: "来源核验未通过。", errors: ["场景1没有来源。"]}));
    expect(message).toContain("来源核验未通过");
    expect(message).toContain("场景1没有来源");
  });
});
