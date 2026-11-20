package com.horsecoder.common.whuTalent.skilllab;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@Profile("registry")
@RequestMapping("/skills")
class RegistryController {
    private final Map<String, SkillDefinition> skills = new HashMap<>();
    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();
    private final String instance = UUID.randomUUID().toString();
    private final int capacity;

    RegistryController(@Value("${lab.capacity:100000}") int capacity) {
        this.capacity = capacity;
    }

    @PostMapping("/batch")
    @ResponseStatus(HttpStatus.CREATED)
    Map<String, Integer> register(@RequestBody List<String> markdown) {
        if (markdown.isEmpty() || markdown.size() > 1000) throw SkillDefinition.bad("Batch size must be 1–1000");
        var additions = new HashMap<String, SkillDefinition>();
        for (String text : markdown) {
            var skill = SkillDefinition.parse(text);
            if (additions.putIfAbsent(skill.name(), skill) != null) throw conflict("Duplicate name in batch");
        }
        lock.writeLock().lock();
        try {
            if (additions.keySet().stream().anyMatch(skills::containsKey)) throw conflict("Skill already registered");
            if (additions.size() > capacity - skills.size()) throw conflict("Registry capacity reached");
            skills.putAll(additions);
            return Map.of("registered", additions.size(), "count", skills.size());
        } finally {
            lock.writeLock().unlock();
        }
    }

    @GetMapping("/stats")
    Map<String, Object> stats() {
        lock.readLock().lock();
        try {
            return Map.of("count", skills.size(), "capacity", capacity, "instance", instance);
        } finally {
            lock.readLock().unlock();
        }
    }

    @GetMapping("/{name}")
    SkillDefinition get(@PathVariable String name) {
        lock.readLock().lock();
        try {
            var result = skills.get(name);
            if (result == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Skill not registered");
            return result;
        } finally {
            lock.readLock().unlock();
        }
    }

    @DeleteMapping("/{name}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void unload(@PathVariable String name) {
        lock.writeLock().lock();
        try {
            if (skills.remove(name) == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "Skill not registered");
        } finally {
            lock.writeLock().unlock();
        }
    }

    private ResponseStatusException conflict(String message) {
        return new ResponseStatusException(HttpStatus.CONFLICT, message);
    }
}
