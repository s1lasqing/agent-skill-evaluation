package com.horsecoder.common.whuTalent.skilllab;

import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import org.yaml.snakeyaml.LoaderOptions;
import org.yaml.snakeyaml.Yaml;
import org.yaml.snakeyaml.constructor.SafeConstructor;

record SkillDefinition(String name, String description, String kind, String suffix, String instructions) {
    private static final Pattern FRONTMATTER = Pattern.compile(
        "\\A\\uFEFF?---[ \\t]*\\R(.*?)^---[ \\t]*\\R(.*)\\z",
        Pattern.MULTILINE | Pattern.DOTALL);
    private static final Pattern NAME = Pattern.compile("[a-z0-9][a-z0-9-]{0,62}");

    static SkillDefinition parse(String markdown) {
        if (markdown == null || markdown.length() > 32768) throw bad("Invalid SKILL.md length");
        var match = FRONTMATTER.matcher(markdown);
        if (!match.matches() || match.group(2).isBlank()) throw bad("Expected YAML frontmatter and Markdown");
        var options = new LoaderOptions();
        options.setAllowDuplicateKeys(false);
        options.setCodePointLimit(32768);
        options.setMaxAliasesForCollections(0);
        Object data;
        try {
            data = new Yaml(new SafeConstructor(options)).load(match.group(1));
        } catch (RuntimeException error) {
            throw bad("Invalid YAML frontmatter");
        }
        if (!(data instanceof Map<?, ?> meta) || !(meta.get("name") instanceof String name)
                || !NAME.matcher(name).matches() || !(meta.get("description") instanceof String description)
                || description.isBlank()) throw bad("Expected valid name and description");
        var operation = meta.get("operation");
        var argument = meta.get("suffix");
        if ("cleanup".equals(operation)) return new SkillDefinition(name, description, "cleanup", "", match.group(2));
        if ("append".equals(operation) && argument instanceof String suffix && !suffix.isEmpty()
                && suffix.length() <= 64) return new SkillDefinition(name, description, "append", suffix, match.group(2));
        throw bad("Unsupported operation or suffix");
    }

    static ResponseStatusException bad(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }
}
