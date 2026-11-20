package com.horsecoder.common.whuTalent.skilllab;

import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.*;

record WorkerRequest(SkillDefinition skill, String text) {}
record WorkerResult(String text) {}

@RestController
@Profile("worker")
class WorkerController {
    @PostMapping("/execute")
    WorkerResult execute(@RequestBody WorkerRequest request) {
        if (request.skill() == null || request.text() == null || request.text().length() > 16384) {
            throw SkillDefinition.bad("Invalid skill or input length");
        }
        var text = request.text();
        var skill = request.skill();
        return switch (skill.kind()) {
            case "cleanup" -> new WorkerResult(text.strip()
                .replaceFirst("(?i)^(certainly|of course|absolutely|great question|sure thing|definitely)!\\s*", "")
                .replaceAll("[ \\t]+", " ")
                .replaceAll("(?m) +$", "").replaceAll("\\R(?: *\\R){2,}", "\n\n"));
            case "append" -> new WorkerResult(text + skill.suffix());
            default -> throw SkillDefinition.bad("Unsupported operation");
        };
    }
}
