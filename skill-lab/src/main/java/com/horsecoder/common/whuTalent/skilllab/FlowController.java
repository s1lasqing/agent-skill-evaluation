package com.horsecoder.common.whuTalent.skilllab;

import feign.FeignException;
import java.util.List;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@FeignClient(name = "skill-registry")
interface RegistryClient {
    @GetMapping("/skills/{name}")
    SkillDefinition get(@PathVariable("name") String name);
}

@FeignClient(name = "skill-worker")
interface WorkerClient {
    @PostMapping("/execute")
    WorkerResult execute(@RequestBody WorkerRequest input);
}

record ChainRequest(List<String> skills, String input) {}
record ChainResult(List<String> skills, String output) {}

@RestController
@Profile("flow")
class FlowController {
    private final RegistryClient registry;
    private final WorkerClient worker;

    FlowController(RegistryClient registry, WorkerClient worker) {
        this.registry = registry;
        this.worker = worker;
    }

    @PostMapping("/flow")
    ChainResult run(@RequestBody ChainRequest chain) {
        if (chain.skills() == null || chain.skills().isEmpty() || chain.skills().size() > 100
                || chain.input() == null || chain.input().length() > 8192
                || chain.skills().stream().anyMatch(s -> s == null || !s.matches("[a-z0-9][a-z0-9-]{0,62}"))) {
            throw SkillDefinition.bad("Expected 1–100 valid skill names and input at most 8192 chars");
        }
        String value = chain.input();
        for (String name : chain.skills()) {
            SkillDefinition skill;
            try {
                skill = registry.get(name);
            } catch (FeignException.NotFound missing) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Skill not registered: " + name);
            } catch (FeignException failed) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Registry unavailable");
            }
            try {
                value = worker.execute(new WorkerRequest(skill, value)).text();
            } catch (FeignException failed) {
                throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Skill execution failed: " + name);
            }
        }
        return new ChainResult(chain.skills(), value);
    }
}
